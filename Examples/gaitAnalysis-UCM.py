'''
    ---------------------------------------------------------------------------
    OpenCap processing: example_gait_analysis.py
    ---------------------------------------------------------------------------
    Copyright 2023 Stanford University and the Authors
    
    Author(s): Scott Uhlrich
    
    Licensed under the Apache License, Version 2.0 (the "License"); you may not
    use this file except in compliance with the License. You may obtain a copy
    of the License at http://www.apache.org/licenses/LICENSE-2.0
    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.
                
    Please contact us for any questions: https://www.opencap.ai/#contact

    This example shows how to run a kinematic analysis of gait data. It works
    with either treadmill or overground gait. You can compute scalar metrics 
    as well as gait cycle-averaged kinematic curves.
    
'''

import os
import sys
import numpy as np
# import math
import zipfile
import tkinter as tk
from tkinter import filedialog
import csv
import re
# import openpyxl

os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
assert os.path.exists('VENDORING.md'), (
    'chdir landed on ' + os.getcwd() + ', which does not look like the repo root '
    '(no VENDORING.md there) -- this script must stay inside its original Examples/ folder.')
sys.path.append(os.path.abspath("./"))
# sys.path.append(os.path.abspath("./"))
sys.path.append(os.path.abspath("./ActivityAnalyses"))
sys.path.append(os.path.abspath("../ActivityAnalyses"))

# from tkinter import filedialog
from gait_analysis_UCM import gait_analysis
from utils import get_trial_id, download_trial, get_user_sessions, download_session
# from utilsPlotting import plot_dataframe_with_shading
import utils
# import utilsKinematics

import opensim as osim
from scipy.spatial.transform import Rotation as R
from io import StringIO
import statistics

# %% Paths.
baseDir = os.path.join(os.getcwd(), '..')
dataFolder = os.path.join(baseDir, 'Data')
msflag=0
sciflag=0

# %% GDI Variables
parDir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))     #find the parent directory of the files

for root, dirs, files in os.walk(parDir):               #walk through the directory tree to search for files
    if 'matrix.csv' in files:                           #if matrix file found
        file_path = os.path.join(root, 'matrix_ms_reduced.csv')    #open and read the contents
        with open(file_path, 'r') as file:
            matrix = list(csv.reader(file))             
            matrix = np.array(matrix, dtype=float)      #convert to NumPy array
            matrix = np.transpose(np.array(matrix))     #transpose matrix
    if 'perGaitCycle.csv' in files:
        file_path = os.path.join(root, 'perGaitCycle.csv')
        with open(file_path, 'r') as file:
            perGaitCycle = list(csv.reader(file))
    if 'controlCalc.csv' in files:
        file_path = os.path.join(root, 'controlCalc_ms_reduced.csv')
        with open(file_path, 'r') as file:
            controlCalc = csv.reader(file)
            controlCalc = [float(value) for row in controlCalc for value in row] #nested list comprehendsion to flatten the 2D list
    
#%%   

def getpelvis(model_filename,coordinatesFileName):
    osim.Logger.setLevel(5)
    for root, dirs, files in os.walk(model_filename):
        for file in files:
            if file.endswith(".yaml"):
                metadat=root
    modelName = utils.get_model_name_from_metadata(metadat)
    modelPath = os.path.join(metadat,'OpenSimData', 'Model',modelName)
    motionPath = os.path.join(metadat, 'OpenSimData', 'Kinematics',
                               '{}.mot'.format(coordinatesFileName))
    myModel=osim.Model(modelPath)
    state=myModel.initSystem()
    analyze=osim.AnalyzeTool(myModel)
    analyze.setName('analyze')
    analyze.setCoordinatesFileName(motionPath)
    analyze.loadStatesFromFile(state)
    analyze.run()
    q=osim.TimeSeriesTable(motionPath)
    time=q.getIndependentColumn()
    state=myModel.initSystem()
    points=[]
    direction=[]
    heading=[]
    pelv=myModel.getBodySet().get('pelvis')
    for i,ii in enumerate(time):
        value=osim.RowVector(q.getRowAtIndex(i));
        for j, coordinate in enumerate(myModel.updCoordinateSet()):
            if j<33:
                coordinate.setValue(state,np.radians(value[j]),False);
        myModel.realizePosition(state)
        r=pelv.getPositionInGround(state).to_numpy()
        direction.append([float(r[0]),float(r[1]),float(r[2])])
        
    direction=np.array(direction)    
    x2=statistics.mean(direction[-4:,0])
    x1=statistics.mean(direction[0:4,0])
    y2=statistics.mean(direction[-4:,1])
    y1=statistics.mean(direction[0:4,1])
    heading=np.degrees(np.arctan2([y2-y1],[x2-x1]))[0]
        
        
    for i,ii in enumerate(time):
        value=osim.RowVector(q.getRowAtIndex(i));
        for j, coordinate in enumerate(myModel.updCoordinateSet()):
            if j<33:
                coordinate.setValue(state,np.radians(value[j]),False);

        myModel.realizePosition(state)

        rcalc=myModel.getBodySet().get('calcn_r')
        post2=rcalc.getRotationInGround(state)
        t4=np.genfromtxt(StringIO(osim.Mat33(post2).toString().replace("["," ").replace("]"," ")[1::]),delimiter=",")
        r2=R.from_matrix(t4).as_euler('xyz',degrees=True)-5
        lcalc=myModel.getBodySet().get('calcn_l')
        post3=lcalc.getRotationInGround(state)
        t5=np.genfromtxt(StringIO(osim.Mat33(post3).toString().replace("["," ").replace("]"," ")[1::]),delimiter=",")
        r3=R.from_matrix(t5).as_euler('xyz',degrees=True)+5
        
        points.append([time[i],heading,float(r2[1]),float(r3[1]),float(r2[1])-heading,heading-float(r3[1])]);
        
    fpa_r=np.array(points)[:,4]
    fpa_l=np.array(points)[:,5]
    return fpa_r, fpa_l

response='';
looped=0;
while True: 
#ask user what they want to do
    if response.lower()!='z':
        print("What would you like to do?")
        print("[P] Pull data from online to download")
        print("[Z] Select a zipped folder to evaluate")
        print("[E] Evaluate downloaded data")
        response = input("").lower()
        
    if response.lower() == 'p':
    # find sessions online
        sessions = get_user_sessions()
        sessionList = [session['id'] for session in sessions]
        # base directory for downloads. Specify None if you want to go to os.path.join(os.getcwd(),'Data')
        downloadPath = os.path.join(os.getcwd(),'Data')
        
        # Filter out sessions that have already been downloaded
        availableSessions = []
        for session_id in sessionList:
            session_path = os.path.join(downloadPath, 'OpenCapData_' + session_id)
            if not os.path.exists(session_path):
                availableSessions.append(session_id)
    
        # If no sessions are available, print a message and return to the main menu
        if not availableSessions:
            print("\nNo available sessions.\n")
            continue
    
        print()
        print("Available sessions:")
        print("0. All sessions")
        for i, session in enumerate(availableSessions, start=1):
            print(f"{i}. {session}")
    
        # Handle user input to select sessions for download
        selectedSessions = []
        while True:
            selected_indices = input("Enter the indices of the sessions to download (comma-separated) or [M] for the main menu: ")
            if selected_indices.lower() == 'm':
                break
            if selected_indices == '0':
                selectedSessions = availableSessions[:]  # Select all sessions as a copy of availableSessions
                break
            selected_indices = [int(index) for index in selected_indices.split(',') if 0 < int(index) <= len(availableSessions)]
            selectedSessions = [availableSessions[index - 1] for index in selected_indices]
            break  # Exit the loop after handling user input
       
        for session_id in selectedSessions:
            # Check if the session folder already exists
            session_path = os.path.join(downloadPath, 'OpenCapData_' + session_id)
            if os.path.exists(session_path):
                print(f"Session {session_id} already downloaded. Skipping...\n")
            else:
                # If only interested in marker and OpenSim data, downladVideos=False will be faster
                download_session(session_id,sessionBasePath=downloadPath,downloadVideos=True)

    elif response.lower() == 'e':
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        root.wm_attributes('-topmost',1)
                            
        # Prompt the user to select a file from the specified folder
        filePath = filedialog.askdirectory(parent=root, initialdir=os.path.join(os.getcwd(),'Data'))
        session_id = re.search(r'OpenCapData_(.+)', filePath).group(1)
        
        folderName = filePath[filePath.rfind("/")+1:filePath.rfind("_")]
        if folderName.find('.z')!=-1:
            folderName=filePath[filePath.rfind("/")+1:filePath.rfind(".zip")]
                            
    elif response.lower() == 'z':
        # select and unzip downloaded folder
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost',1)
        filePath = filedialog.askopenfilename(parent=root)
        
    
        with zipfile.ZipFile(filePath, 'r') as zip_ref:
            zip_ref.extractall(filePath[:filePath.rfind("_")])
            # folderName = filePath[filePath.rfind("/")+1:filePath.rfind(".zip")]
            folderName = filePath[filePath.rfind("/")+1:filePath.rfind("_")]
            if folderName.find('.z')!=-1:
                folderName=filePath[filePath.rfind("/")+1:filePath.rfind(".zip")]
            
            subjid=filePath[filePath[0:filePath.rfind("/",filePath.rfind("/"))].rfind("/")+1:filePath.rfind("/",filePath.rfind("/"))];
            savpath=filePath[0:filePath.rfind("/",filePath.rfind("/"))]
        
            if filePath:
                firstInd = filePath.find("Data_") + len("Data_")
                # session_id = filePath[firstInd:filePath.rfind(".zip",firstInd)]
                #no idea when one works vs the other
                session_id = filePath[firstInd:filePath.rfind("_",firstInd)]
                if session_id.find('.z')!=-1:
                    session_id=filePath[firstInd:filePath.rfind(".zip",firstInd)]
            else:
                print("No file selected.")

#%%
    if response.lower() != 'p':
    #look for trial names
        trialNames = []
        if response.lower() == 'e':
            baseFolder = filePath[:filePath.rfind("_")]+"/"+folderName
            for root, dirs, files in os.walk(filePath):
                for file in files:
                    if file.endswith('.mot'):
                        trialNames.append(file[:-4])
        elif response.lower() == 'z':     
            baseFolder = filePath[:filePath.rfind("_")]+"/"+folderName
            for root, dirs, files in os.walk(baseFolder):
                for file in files:
                    if file.endswith(".mot"):
                        trialNames.append(file[:-4])
                
        print()
        print("Available trials:")
        for i, trial in enumerate(trialNames, start=1):
            if trial != "neutral":
                print(f"{i}. {trial}")
    
        while True:
            try:
                selected_index = int(input("Enter the index of the trial to run: "))-1
                if 0 <= selected_index < len(trialNames):
                    trial_name = trialNames[selected_index]
                    break
            except ValueError:
                print("Invalid input")

        print()
    
        scalar_names = {'gait_speed', 'stride_length', 'step_width', 'cadence',
                    'single_support_time', 'double_support_time', 'step_length_symmetry'}
    
        # Select how many gait cycles you'd like to analyze. Select -1 for all gait
        # cycles detected in the trial.
        n_gait_cycles = -1
    
        # Select lowpass filter frequency for kinematics data.a
        filter_frequency = 6
        trimming_start = -1
        trimming_end = -1
        # %% Gait analysis.
        # Get trial id from name.
        trial_id = get_trial_id(session_id, trial_name)
    
        # Set session path.
        sessionDir = os.path.join(dataFolder, session_id)
        
        # Download data.
        trialName = download_trial(trial_id, sessionDir, session_id=session_id)
        
        [fpa_r, fpa_l]=getpelvis(baseFolder,trialName)

        # Init gait analysis.
        # gait_r = gait_analysis(
        #     sessionDir, trialName, fpa_r,fpa_l, leg='r',
        #     lowpass_cutoff_frequency_for_coordinate_values=filter_frequency,
        #     n_gait_cycles=n_gait_cycles, trimming_start=trimming_start, trimming_end=trimming_end)
        gait_r = gait_analysis(
            baseFolder, trialName, fpa_r,fpa_l, leg='r',
            lowpass_cutoff_frequency_for_coordinate_values=filter_frequency,
            n_gait_cycles=n_gait_cycles, trimming_start=trimming_start, trimming_end=trimming_end)
        gait_l = gait_analysis(
            baseFolder, trialName, fpa_r,fpa_l, leg='l',
            lowpass_cutoff_frequency_for_coordinate_values=filter_frequency,
            n_gait_cycles=n_gait_cycles, trimming_start=trimming_start, trimming_end=trimming_end)
    
    
        center_of_mass={}
        center_of_mass[trialName] = gait_r.get_center_of_mass_values(lowpass_cutoff_frequency=10)
        # Compute scalars and get time-normalized kinematic curves.
        gaitResults = {}
        gaitResults['scalars_r'] = gait_r.compute_scalars(scalar_names)
        gaitResults['curves_r'] = gait_r.get_coordinates_normalized_time()
        gaitResults['scalars_l'] = gait_l.compute_scalars(scalar_names)
        gaitResults['curves_l'] = gait_l.get_coordinates_normalized_time()
    
        # %% Print scalar results.
        print('\nRight foot gait metrics:')
        print('-----------------')
        for key, value in gaitResults['scalars_r'].items():
            rounded_value = round(value['value'], 2)
            print(f"{key}: {rounded_value} {value['units']}")
    
        print('\nLeft foot gait metrics:')
        print('-----------------')
        for key, value in gaitResults['scalars_l'].items():
            rounded_value = round(value['value'], 2)
            print(f"{key}: {rounded_value} {value['units']}")
    
        # %% You can plot multiple curves, in this case we compare right and left legs.
    
        joint_names = ['pelvis_tilt',	'pelvis_list',	'pelvis_rotation',	'pelvis_tx',	'pelvis_ty',	'pelvis_tz',	
                       'hip_flexion_r',	'hip_adduction_r',	'hip_rotation_r',	'knee_angle_r',	'ankle_angle_r',	'subtalar_angle_r',	
                       'mtp_angle_r',	'hip_flexion_l',	'hip_adduction_l',	'hip_rotation_l',	'knee_angle_l',	'ankle_angle_l',	
                       'subtalar_angle_l',	'mtp_angle_l',	'lumbar_extension',	'lumbar_bending',	'lumbar_rotation',	'arm_flex_r',	
                       'arm_add_r',	'arm_rot_r',	'elbow_flex_r',	'pro_sup_r',	'arm_flex_l',	'arm_add_l',	'arm_rot_l',	'elbow_flex_l',	'pro_sup_l','comx','comy','comz']

        data = []

    
        for k in joint_names:
            # print(joint_names[k])
            for num in range(101):
                # if (num % 2 == 0):
                if (k == 'pelvis_tilt'):
                    #print(gaitResults['curves_r']['mean'][k][num]+20)
                    data.append(gaitResults['curves_r']['mean'][k][num]+20)
                elif (k == 'pelvis_rotation'):
                    if (gaitResults['curves_r']['mean'][k][num] > 180):
                        data.append((gaitResults['curves_r']['mean'][k][num]-180))
                        #print((gaitResults['curves_r']['mean'][k][num]-180))
                    else:
                        data.append(gaitResults['curves_r']['mean'][k][num])
                        #print(gaitResults['curves_r']['mean'][k][num])
                elif (k=='comx'):
                    data.append(gaitResults['curves_r']['mean'][k][num]-gaitResults['curves_r']['mean']['pelvis_tx'][num])
                elif (k=='comy'):
                    data.append(gaitResults['curves_r']['mean'][k][num]-gaitResults['curves_r']['mean']['pelvis_ty'][num])
                elif (k=='comz'):
                    data.append(gaitResults['curves_r']['mean'][k][num]-gaitResults['curves_r']['mean']['pelvis_tz'][num])
                else:
                    data.append(gaitResults['curves_r']['mean'][k][num])
                    #print(gaitResults['curves_r']['mean'][k][num])
    
        # % Calculate the GDI
        # value = np.array(data)
        # subject = np.dot(matrix, value)
        # diff = subject - controlCalc
    
        # ln_result = math.log(math.sqrt(np.sum(np.square(diff)) ))  # natural log of the euclidean distance between subjects and controls
        # z_score = (ln_result - 4.443685139)/0.223457646 #The z-score is found by subtracting the average natural log accross all subjects to the ln_result and dividing by the SD of the average NL
        # GDI_r = 100 - (10*z_score)
        # print()
        # print("Right GDI: ")
        # print(GDI_r)
        # #uncomment the print lines if you want to check GDI score with excel sheet
    
        # joint_names2 =['pelvis_tilt', 'pelvis_list', 'pelvis_rotation', 'hip_flexion_l', 
        #                 'hip_adduction_l', 'hip_rotation_l', 'knee_angle_l', 'ankle_angle_l', 'subtalar_angle_l']
        # data = []
        # indiv_data=np.zeros([len(joint_names)*101,len(gaitResults['curves_r']['indiv'])])
        
    
        # for k in joint_names2:
        #     for num in range(101):
        #         if (num % 2 == 0):
        #             if (k == 'pelvis_tilt'):
        #                 #print(gaitResults['curves_l']['mean'][k][num]+20)
        #                 data.append(gaitResults['curves_l']['mean'][k][num]+20)
        #             elif (k =='pelvis_rotation'):
        #                 if (gaitResults['curves_l']['mean'][k][num] >180):
        #                     #print((gaitResults['curves_l']['mean'][k][num]-180))
        #                     data.append((gaitResults['curves_l']['mean'][k][num]-180))
        #                 else:
        #                     #print(gaitResults['curves_l']['mean'][k][num])
        #                     data.append(gaitResults['curves_l']['mean'][k][num])
        #             else:
        #                 #print(gaitResults['curves_l']['mean'][k][num])
        #                 data.append(gaitResults['curves_l']['mean'][k][num])
    
    
        indiv_data=np.zeros([len(joint_names)*101,len(gaitResults['curves_r']['indiv'])])
        
        for rcou in range(0,len(gaitResults['curves_r']['indiv'])):
            rowcou=0
            for k in joint_names:
                for num in range(101):
                    
                    if (k=='pelvis_tilt'):
                        indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]+20
                        rowcou+=1
                    elif (k=='pelvis_rotation'):
                        if(gaitResults['curves_r']['indiv'][rcou][k][num] > 180):
                            indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-180
                            rowcou+=1
                        else:
                            indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]
                            rowcou+=1
                    elif (k=='comx'):
                        indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-gaitResults['curves_r']['indiv'][rcou]['pelvis_tx'][num]
                        rowcou+=1
                    elif (k=='comy'):
                        indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-gaitResults['curves_r']['indiv'][rcou]['pelvis_ty'][num]
                        rowcou+=1
                    elif (k=='comz'):
                        indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-gaitResults['curves_r']['indiv'][rcou]['pelvis_tz'][num]
                        rowcou+=1
                    else:
                        indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]
                        rowcou+=1
                        
                            
        np.savetxt(savpath + '/' + subjid + '-' + trial_name + '_right.csv', indiv_data, delimiter=',', fmt='%f') 
        
        # # % Calculate the GDI
        # value = np.array(data)
        # subject = np.dot(matrix, value)
        # diff = subject - controlCalc
        
        # ln_result = math.log(math.sqrt(np.sum(np.square(diff)) ))  # natural log of the euclidean distance between subjects and controls
        # z_score = (ln_result - 4.443685139)/0.223457646 #The z-score is found by subtracting the average natural log accross all subjects to the ln_result and dividing by the SD of the average NL
        # GDI_l = 100 - (10*z_score)
        # print()
        # print("Left GDI: ")
        # print(GDI_l)
    
        # #get the GDI average
        # avg = (GDI_r + GDI_l)/2
        # print()
        # print("Average GDI: ")
        # print(avg)
        # print()
    
        # plot_dataframe_with_shading(
        #     [gaitResults['curves_r']['mean'], gaitResults['curves_l']['mean']],
        #     [gaitResults['curves_r']['sd'], gaitResults['curves_l']['sd']],
        #     leg = ['r', 'l'],
        #     xlabel= '% gait cycle',
        #     title= 'kinematics (m or deg)',
        #     legend_entries = ['right', 'left'])
    
        # # %%
        # #save to the excel file
        # directory = r'C:\Users\loshea\repo\opencap-processingSRAL\Data'
        # fileName = os.path.join(directory,'GaitGDI.xlsx')
        
        # if not os.path.exists(fileName): #if the workbook does not exist
        #     workbook = openpyxl.Workbook() #create a new workbook
        #     sheet = workbook.active #select the active worksheet
        #     sheet['A1'] = 'Session ID'
        #     sheet['B1'] = 'Date (YYYY-MM-DD)'
        #     sheet['C1'] = 'Sub Name'
        #     sheet['D1'] = 'Trial'
        #     sheet['E1'] = 'Right GDI'
        #     sheet['F1'] = 'Left GDI'
        #     sheet['G1'] = 'Average GDI'
        #     nextRow = sheet.max_row + 1
        
        # else:
        #     workbook = openpyxl.load_workbook(fileName)
        #     sheet = workbook.active
        #     nextRow = 2

        # for root, dirs, files in os.walk(directory + "\OpenCapData_" + session_id):
        #     for file in files:
        #         if file =='sessionData.txt':
        #             metaData = os.path.join(root,file)
        #             print(metaData)
                    
        #             # Open the file in read mode
        #             with open(metaData, 'r') as file:
        #                 # Read each line of the file
        #                 for line in file:
        #                     # Split each line into label and value
        #                     label, value = line.strip().split(":")

        #                     # Check the label and assign the value to the corresponding variable
        #                     if label.strip() == "Session":
        #                         session_id = value.strip()
        #                     elif label.strip() == "Subject Name":
        #                         subName = value.strip()
        #                     elif label.strip() == "Date":
        #                         date = value.strip()
        
    
        # sheet[f'A{nextRow}'] = session_id
        # sheet[f'B{nextRow}'] = date
        # sheet[f'C{nextRow}'] = subName
        # sheet[f'D{nextRow}'] = trial_name
        # sheet[f'E{nextRow}'] = GDI_r
        # sheet[f'F{nextRow}'] = GDI_l
        # sheet[f'G{nextRow}'] = avg
    
        # workbook.save(fileName) #save workbook
        
        #ask user if they want to run another trial
        response = input("Do you want to run another trial? [Y/N]: ").lower()
    
        if response.lower() != 'y':
            break
        looped=1

# while True:
#     # try:
#         # selected_index = int(input("1)Uninjured\n2)SCI\n3)MS\nEnter Condition: "))-1
#     selected_index=2
#     if selected_index==0:
#         with open(r'..\matrix_control.csv', 'r') as file:
#             matrix = list(csv.reader(file))
#             matrix = np.array(matrix, dtype=float)
#             #matrix = matrix.reshape((459,21))
#             matrix = np.transpose(np.array(matrix))
#         with open(r'..\perGaitCycle.csv', 'r') as file:
#             perGaitCycle = list(csv.reader(file))
#         with open(r'..\controlCalc_control.csv', 'r') as file:
#             controlCalc = csv.reader(file)
#             controlCalc = [float(value) for row in controlCalc for value in row]                                     
#         with open(r'..\control_kinematics.csv','r')as filec:
#             ckine=list(csv.reader(filec,delimiter=","))
#             ckine=np.array(ckine, dtype=float)
#         break
    
#     elif selected_index==1:
#         with open(r'..\matrix.csv', 'r') as file:
#             matrix = list(csv.reader(file))
#             matrix = np.array(matrix, dtype=float)
#             #matrix = matrix.reshape((459,21))
#             matrix = np.transpose(np.array(matrix))
#         with open(r'..\perGaitCycle.csv', 'r') as file:
#             perGaitCycle = list(csv.reader(file))
#         with open(r'..\controlCalc_sci_v2.csv', 'r') as file:
#             controlCalc = csv.reader(file)
#             controlCalc = [float(value) for row in controlCalc for value in row]               
#         sciflag=1                      
#         break
#     elif selected_index==2:
#         with open(r'..\matrix_ms_reduced.csv', 'r') as file:
#             matrix = list(csv.reader(file))
#             matrix = np.array(matrix, dtype=float)
#             #matrix = matrix.reshape((459,21))
#             matrix = np.transpose(np.array(matrix))
#         with open(r'..\perGaitCycle.csv', 'r') as file:
#             perGaitCycle = list(csv.reader(file))
#         with open(r'..\controlCalc_ms_reduced.csv', 'r') as file:
#             controlCalc = csv.reader(file)
#             controlCalc = [float(value) for row in controlCalc for value in row]                                     
#         msflag=1
#         break
#     # except ValueError:
#     #     print("Invalid input")
# print()


# def getpelvis(model_filename,coordinatesFileName):
#     osim.Logger.setLevel(5)
#     modelName = utils.get_model_name_from_metadata(model_filename)
#     modelPath = os.path.join(baseFolder,'OpenSimData', 'Model',modelName)
#     motionPath = os.path.join(model_filename, 'OpenSimData', 'Kinematics',
#                                '{}.mot'.format(coordinatesFileName))
#     myModel=osim.Model(modelPath)
#     state=myModel.initSystem()
#     analyze=osim.AnalyzeTool(myModel)
#     analyze.setName('analyze')
#     analyze.setCoordinatesFileName(motionPath)
#     analyze.loadStatesFromFile(state)
#     analyze.run()
#     q=osim.TimeSeriesTable(motionPath)
#     time=q.getIndependentColumn()
#     state=myModel.initSystem()
#     points=[]
#     direction=[]
#     heading=[]
#     pelv=myModel.getBodySet().get('pelvis')
#     for i,ii in enumerate(time):
#         value=osim.RowVector(q.getRowAtIndex(i));
#         for j, coordinate in enumerate(myModel.updCoordinateSet()):
#             if j<33:
#                 coordinate.setValue(state,np.radians(value[j]),False);
#         myModel.realizePosition(state)
#         r=pelv.getPositionInGround(state).to_numpy()
#         direction.append([float(r[0]),float(r[1]),float(r[2])])
        
#     direction=np.array(direction)    
#     x2=statistics.mean(direction[-4:,0])
#     x1=statistics.mean(direction[0:4,0])
#     y2=statistics.mean(direction[-4:,1])
#     y1=statistics.mean(direction[0:4,1])
#     heading=np.degrees(np.arctan2([y2-y1],[x2-x1]))[0]
        
        
#     for i,ii in enumerate(time):
#         value=osim.RowVector(q.getRowAtIndex(i));
#         for j, coordinate in enumerate(myModel.updCoordinateSet()):
#             if j<33:
#                 coordinate.setValue(state,np.radians(value[j]),False);

#         myModel.realizePosition(state)

#         rcalc=myModel.getBodySet().get('calcn_r')
#         post2=rcalc.getRotationInGround(state)
#         t4=np.genfromtxt(StringIO(osim.Mat33(post2).toString().replace("["," ").replace("]"," ")[1::]),delimiter=",")
#         r2=R.from_matrix(t4).as_euler('xyz',degrees=True)-5
#         lcalc=myModel.getBodySet().get('calcn_l')
#         post3=lcalc.getRotationInGround(state)
#         t5=np.genfromtxt(StringIO(osim.Mat33(post3).toString().replace("["," ").replace("]"," ")[1::]),delimiter=",")
#         r3=R.from_matrix(t5).as_euler('xyz',degrees=True)+5
        
#         points.append([time[i],heading,float(r2[1]),float(r3[1]),float(r2[1])-heading,heading-float(r3[1])]);
        
#     fpa_r=np.array(points)[:,4]
#     fpa_l=np.array(points)[:,5]
#     return fpa_r, fpa_l


# %% GDI Variables



    
# %% User-defined variables.
# Select example: options are treadmill and overground.
# example = 'overground'

# if example == 'treadmill':
#     session_id = '4d5c3eb1-1a59-4ea1-9178-d3634610561c' # 1.25m/s
#     trial_name = 'walk_1_25ms'

# elif example == 'overground':
#     session_id = 'b39b10d1-17c7-4976-b06c-a6aaf33fead2'
#     trial_name = 'gait_3'


# %% select and unzip downloaded folder
# root = tk.Tk()
# root.withdraw()
# root.wm_attributes('-topmost', 1)
# filePath = filedialog.askopenfilename(parent=root)



# with zipfile.ZipFile(filePath, 'r') as zip_ref:
#     zip_ref.extractall(filePath[:filePath.find("_")])
#     folderName = filePath[filePath.rfind("/")+1:filePath.rfind("_")]          #
#     # print(folderName)

# # print(filePath[filePath.rfind("/",filePath.rfind("/",filePath.rfind("/"))):filePath.rfind("/",filePath.rfind("/"))])
# subjid=filePath[filePath[0:filePath.rfind("/",filePath.rfind("/"))].rfind("/")+1:filePath.rfind("/",filePath.rfind("/"))];
# savpath=filePath[0:filePath.rfind("/",filePath.rfind("/"))]
# # print(savpath)

# if filePath:
#     firstInd = filePath.find("Data_") + len("Data_")
#     session_id = filePath[firstInd:filePath.find("_",firstInd)]
# else:
#     print("No file selected.")

# while True:
#     #look for trial names
#     trialNames = []
#     baseFolder = filePath[:filePath.find("_")]+"/" + folderName
#     # print(filePath)               #
#     # print(baseFolder)
#     # print(subjid)
#     for root, dirs, files in os.walk(baseFolder):
#         for file in files:
#             if file.endswith(".trc"):
#                 trialNames.append(file[:-4])
                
#     print()
#     print("Available trials:")
#     for i, trial in enumerate(trialNames, start=1):
#         print(f"{i}. {trial}")
    
#     while True:
#         try:
#             selected_index = int(input("Enter the index of the trial to run: "))-1
#             if 0 <= selected_index < len(trialNames):
#                 trial_name = trialNames[selected_index]
#                 trialNames.clear()                                            #
#                 break
#         except ValueError:
#             print("Invalid input")
#     print()
    
#     # while True:
#     #     try:
#     #         trimming_start=float(input("Enter the trim start or type 0 to skip: "))
#     #         if  trimming_start==0:
#     #             trimming_start=-1
#     #         trimming_end=float(input("Enter the trim end or type 0 to skip: "))
#     #         if trimming_end==0:
#     #             trimming_end=-1
#     #             break
#     #         break
#     #     except ValueError:
#     #         print("invalid input")
#     trimming_start=-1
#     trimming_end=-1
#     print()
    
#     scalar_names = {'gait_speed', 'stride_length', 'step_width', 'cadence',
#                     'double_support_time', 'step_length_symmetry'}
    
#     # Select how many gait cycles you'd like to analyze. Select -1 for all gait
#     # cycles detected in the trial.
#     n_gait_cycles = -1
    
#     # Select lowpass filter frequency for kinematics data.a
#     filter_frequency = 6
#     # trimming_start = -1
#     # trimming_end = .75
#     # %% Gait analysis.
#     # Get trial id from name.
#     trial_id = get_trial_id(session_id, trial_name)
    
#     # Set session path.
#     sessionDir = os.path.join(dataFolder, session_id)
#     # print(sessionDir)
#     # modelName = utils.get_model_name_from_metadata(sessionDir)
#     # print(modelName)
#     # Download data.
#     trialName = download_trial(trial_id, sessionDir, session_id=session_id)
#     [fpa_r, fpa_l]=getpelvis(baseFolder,trialName)
  
    
#     # Init gait analysis.
#     gait_r = gait_analysis(
#         sessionDir, trialName,fpa_r,fpa_l, leg='r',
#         lowpass_cutoff_frequency_for_coordinate_values=filter_frequency,
#         n_gait_cycles=n_gait_cycles, trimming_start=trimming_start, trimming_end=trimming_end)
#     gait_l = gait_analysis(
#         sessionDir, trialName,fpa_r,fpa_l, leg='l',
#         lowpass_cutoff_frequency_for_coordinate_values=filter_frequency,
#         n_gait_cycles=n_gait_cycles, trimming_start=trimming_start, trimming_end=trimming_end)
    
#     center_of_mass={}
#     # center_of_mass = utilsKinematics.kinematics(sessionDir, trialName, lowpass_cutoff_frequency_for_coordinate_values=10)
#     # Get center of mass values, speeds, and accelerations.
#     center_of_mass[trialName] = gait_r.get_center_of_mass_values(lowpass_cutoff_frequency=10)
#     # center_of_mass['speeds'][trial_name] = kinematics[trial_name].get_center_of_mass_speeds(lowpass_cutoff_frequency=10)
#     # center_of_mass['accelerations'][trial_name] = kinematics[trial_name].get_center_of_mass_accelerations(lowpass_cutoff_frequency=10)
#     # gait_r['comx']=center_of_mass[trialName]['x']
#     # gait_r['comy']=center_of_mass[trialName]['y']
#     # gait_r['comz']=center_of_mass[trialName]['z']
#     # print(center_of_mass[trialName]['y'])
#     # input()
    
#     # Compute scalars and get time-normalized kinematic curves.
#     # print(gait_r.segment_walking())
#     gaitResults = {}
#     gaitResults['scalars_r'] = gait_r.compute_scalars(scalar_names)
#     gaitResults['curves_r'] = gait_r.get_coordinates_normalized_time()
#     gaitResults['scalars_l'] = gait_l.compute_scalars(scalar_names)
#     gaitResults['curves_l'] = gait_l.get_coordinates_normalized_time()
    
#     # print(gaitResults['curves_r']['mean'][:])
    
#     # %% Print scalar results.
#     # print('\nRight foot gait metrics:')
#     # print('-----------------')
#     # for key, value in gaitResults['scalars_r'].items():
#     #     rounded_value = round(value['value'], 2)
#     #     print(f"{key}: {rounded_value} {value['units']}")
    
#     # print(str(round(gaitResults['scalars_r']['gait_speed']['value'],2))+"\t"+str(round(gaitResults['scalars_r']['stride_length']['value'],2))+"\t"+str(round(gaitResults['scalars_r']['step_width']['value'],2)*100)+"\t"+str(round(gaitResults['scalars_r']['cadence']['value'],2))+"\t"+str(round(gaitResults['scalars_r']['double_support_time']['value'],2))+"\t"+str(round(gaitResults['scalars_r']['step_length_symmetry']['value'],2)))
   
    
#     # print('\nLeft foot gait metrics:')
#     # print('-----------------')
#     # for key, value in gaitResults['scalars_l'].items():
#     #     rounded_value = round(value['value'], 2)
#     #     print(f"{key}: {rounded_value} {value['units']}")
        
#     # print(str(round(gaitResults['scalars_l']['gait_speed']['value'],2))+"\t"+str(round(gaitResults['scalars_l']['stride_length']['value'],2))+"\t"+str(round(gaitResults['scalars_l']['step_width']['value'],2)*100)+"\t"+str(round(gaitResults['scalars_l']['cadence']['value'],2))+"\t"+str(round(gaitResults['scalars_l']['double_support_time']['value'],2))+"\t"+str(round(gaitResults['scalars_l']['step_length_symmetry']['value'],2)))
    
#     # %% You can plot multiple curves, in this case we compare right and left legs.
    
#     # joint_names = ['pelvis_tilt', 'pelvis_list', 'pelvis_rotation', 'hip_flexion_r',
#     #                'hip_adduction_r', 'hip_rotation_r', 'knee_angle_r', 'ankle_angle_r', 'fpa_r']
#     joint_names = ['pelvis_tilt',	'pelvis_list',	'pelvis_rotation',	'pelvis_tx',	'pelvis_ty',	'pelvis_tz',	
#                    'hip_flexion_r',	'hip_adduction_r',	'hip_rotation_r',	'knee_angle_r',	'ankle_angle_r',	'subtalar_angle_r',	
#                    'mtp_angle_r',	'hip_flexion_l',	'hip_adduction_l',	'hip_rotation_l',	'knee_angle_l',	'ankle_angle_l',	
#                    'subtalar_angle_l',	'mtp_angle_l',	'lumbar_extension',	'lumbar_bending',	'lumbar_rotation',	'arm_flex_r',	
#                    'arm_add_r',	'arm_rot_r',	'elbow_flex_r',	'pro_sup_r',	'arm_flex_l',	'arm_add_l',	'arm_rot_l',	'elbow_flex_l',	'pro_sup_l','comx','comy','comz']

#     data = []

       
    
#     for k in joint_names:
#         # print(k)
#         for num in range(101):
#                 if (k == 'pelvis_tilt'):
#                      #print(gaitResults['curves_r']['mean'][k][num]+20)
#                      data.append(gaitResults['curves_r']['mean'][k][num]+20)
#                 elif (k == 'pelvis_rotation'):
#                      if (gaitResults['curves_r']['mean'][k][num] > 180):
#                          data.append((gaitResults['curves_r']['mean'][k][num]-180))
#                          #print((gaitResults['curves_r']['mean'][k][num]-180))
#                      else:
#                          data.append(gaitResults['curves_r']['mean'][k][num])
#                          #print(gaitResults['curves_r']['mean'][k][num])
#                 elif (k=='comx'):
#                     data.append(gaitResults['curves_r']['mean'][k][num]-gaitResults['curves_r']['mean']['pelvis_tx'][num])
#                 elif (k=='comy'):
#                     data.append(gaitResults['curves_r']['mean'][k][num]-gaitResults['curves_r']['mean']['pelvis_ty'][num])
#                 elif (k=='comz'):
#                     data.append(gaitResults['curves_r']['mean'][k][num]-gaitResults['curves_r']['mean']['pelvis_tz'][num])
                            
#                 # elif (k=='subtalar_angle_r'):
#                 #     data.append()
#                 else:
#                      data.append(gaitResults['curves_r']['mean'][k][num])
#                      #print(gaitResults['curves_r']['mean'][k][num])
    
#     indiv_data=np.zeros([len(joint_names)*101,len(gaitResults['curves_r']['indiv'])])
    
#     for rcou in range(0,len(gaitResults['curves_r']['indiv'])):
#         rowcou=0
#         for k in joint_names:
#             for num in range(101):
                
#                 if (k=='pelvis_tilt'):
#                     indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]+20
#                     rowcou+=1
#                 elif (k=='pelvis_rotation'):
#                     if(gaitResults['curves_r']['indiv'][rcou][k][num] > 180):
#                         indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-180
#                         rowcou+=1
#                     else:
#                         indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]
#                         rowcou+=1
#                 elif (k=='comx'):
#                     indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-gaitResults['curves_r']['indiv'][rcou]['pelvis_tx'][num]
#                     rowcou+=1
#                 elif (k=='comy'):
#                     indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-gaitResults['curves_r']['indiv'][rcou]['pelvis_ty'][num]
#                     rowcou+=1
#                 elif (k=='comz'):
#                     indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-gaitResults['curves_r']['indiv'][rcou]['pelvis_tz'][num]
#                     rowcou+=1
#                 else:
#                     indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]
#                     rowcou+=1
                    
                        
#     np.savetxt(savpath + '/' + subjid + '-' + trial_name + '_right.csv', indiv_data, delimiter=',', fmt='%f') 
    
    # reduceddat=np.concatenate((indiv_data[153:255],indiv_data[306:408]),axis=0)
    # reduceddat=indiv_data[153::]
    # reduceddat=np.concatenate((indiv_data[153:255],indiv_data[306:459]),axis=0)
    # # np.set_printoptions(threshold=sys.maxsize)
    # # print(reduceddat)
    # if np.size(reduceddat,1)>2:
    #      mediandat=np.median(reduceddat,1)
    #      numb=5
    #      n=len(reduceddat)
    #      tris=np.size(reduceddat,1)
    #      singlevariabledepth=np.zeros((numb,tris))
    #      starts=[0, 51, 102, 153, 204, 255]
    #      absmeddistance=np.zeros((n,tris))
    #      for i in range(tris):
    #          for j in range(numb):
    #              singlevariabledepth[j,i]=(sum(abs(reduceddat[starts[j]+1:starts[j+1]-2,i]
    #                                                -mediandat[starts[j]+1:starts[j+1]-2]))+abs(reduceddat[starts[j],i]
    #                                                  -mediandat[starts[j]])+abs(reduceddat[starts[j+1]-1,i]-mediandat[starts[j+1]-1])/2)/50;
                     
    #      overalldepth=np.mean(singlevariabledepth,0)      
    #      c=np.argsort(overalldepth)
    #      ap=np.zeros((1,tris))
    #      features=np.size(matrix,0)
    #      rsco=ap
    #      for i in range(tris):
    #          ap[0,i]=abs(overalldepth[i]-np.median(overalldepth))
    #      medabdev=1.483*np.median(ap)
    #      for i in range(tris):
    #          rsco[0,i]=(overalldepth[i]-np.median(overalldepth))/medabdev
         
    #      data3=reduceddat[:,(abs(rsco)<3).flatten()]
    #      c2=c[(abs(rsco)<3).flatten()]
    #      if len(c2)>5:
    #          data2=reduceddat[:,(c<6).flatten()]
    #      else:
    #          data2=data3
    # else:
    #      data2=reduceddat
         
    # redtris=np.size(data2,1)
    # features=np.size(matrix,0)
    # subject=np.zeros([features,redtris])
    # diff=subject
    # value=data2
     
     
    # if msflag==0:
    #      # ans=data[153:255]+data[306:408]
    #      # print(np.array(ans))
    #      # value = np.array(ans)
    #      for i in range(redtris):
    #          # value[:,i]=data2[:,i]
    #          np.set_printoptions(suppress=True)
    #          subject[:,i]=np.matmul(matrix,value[:,i])
    #      # value=data2
    #      # np.set_printoptions(suppress=True)
    #      # subject = np.matmul(matrix, value)
    # else:
    #     for i in range(redtris):
    #         np.set_printoptions(suppress=True)
    #         subject[:,i]=np.matmul(matrix,value[:,i])
        
    #     # ans=data[153::]
    #     #  value=np.array(ans)
    #     #  np.set_printoptions(suppress=True)
    #     #  subject=np.matmul(matrix,value)
    #  # print(subject)
    # for i in range(redtris):
    #      diff[:,i]=subject[:,i]-controlCalc
    #  # diff = subject - controlCalc
    #  # print(diff)
    # msmean=3.64317
    # mssd=0.54211   
    # z_score=np.zeros(redtris)
    # GDI_r=np.zeros(redtris)
    #  # ln_result = math.log(math.sqrt(np.sum(np.square(diff)) ))  # natural log of the euclidean distance between subjects and controls
    #  # print(ln_result)
    # if sciflag==1:
    #      # z_score = (ln_result - 4.69)/.3 #The z-score is found by subtracting the average natural log accross all subjects to the ln_result and dividing by the SD of the average NL
    #      for i in range(redtris):
    #          ln_result = math.log(math.sqrt(np.sum(np.square(diff[:,i])) ))
    #          z_score[i] = (ln_result - 4.518094)/0.415455
    #          GDI_r[i]=100-(10*z_score[i])
    # elif msflag==1:
    #      # z_score = (ln_result - 4.15466)/0.44206
    #      for i in range(redtris):
    #          ln_result = math.log(math.sqrt(np.sum(np.square(diff[:,i])) ))
    #          z_score[i] = (ln_result - msmean)/mssd
    #          GDI_r[i]=100-(10*z_score[i])
    # else:
    #      z_score = (ln_result - 4.69)/0.30
         
    # print()
    # print("Right GDI: ")
    # if len(GDI_r)>1:
    #     print(GDI_r.mean())
    # else:
    #     print(GDI_r)
    # # % Calculate the GDI
    # # # print(np.array(data))
    # # # value = np.array(data)
    # # # np.set_printoptions(suppress=True)
    # # subject = np.dot(matrix, value)
    # if msflag==0:
    #     ans=data[153:255]+data[306:408]
    #     # print(np.array(ans))
    #     value = np.array(data)
    #     np.set_printoptions(suppress=True)
    #     subject = np.matmul(matrix, value)
    # else:
    #     ans=data[153::]
    #     value=np.array(ans)
    #     np.set_printoptions(suppress=True)
    #     subject=np.matmul(matrix,value)
    # # print(subject)
    # diff = subject - controlCalc
    # # print(diff)
    # msmean=4.23692
    # mssd=0.50750    
    
    # ln_result = math.log(math.sqrt(np.sum(np.square(diff)) ))  # natural log of the euclidean distance between subjects and controls
    # # print(ln_result)
    # if sciflag==1:
    #     # z_score = (ln_result - 4.69)/.3 #The z-score is found by subtracting the average natural log accross all subjects to the ln_result and dividing by the SD of the average NL
    #     z_score = (ln_result - 4.911215)/.252333
    # elif msflag==1:
    #     # z_score = (ln_result - 4.15466)/0.44206
    #     z_score = (ln_result - msmean)/mssd
    # else:
    #     z_score = (ln_result - 4.69)/0.30
    # print(z_score)
    # GDI_r = 100 - (10*z_score)
    # print()
    # print("Right GDI: ")
    # print(GDI_r)
    #uncomment the print lines if you want to check GDI score with excel sheet
    
    # joint_names2 =['pelvis_tilt', 'pelvis_list', 'pelvis_rotation', 'hip_flexion_l', 
    # 'hip_adduction_l', 'hip_rotation_l', 'knee_angle_l', 'ankle_angle_l', 'fpa_l']
    # data = []
    
    
    # # for k in joint_names2:
    # #     for num in range(101):
    # #         if (num % 2 == 0):
    # #             if (k == 'pelvis_tilt'):
    # #                 #print(gaitResults['curves_l']['mean'][k][num]+20)
    # #                 data.append(gaitResults['curves_l']['mean'][k][num]*-1+20)
    # #             elif (k =='pelvis_rotation'):
    # #                 if (gaitResults['curves_l']['mean'][k][num] >180):
    # #                     #print((gaitResults['curves_l']['mean'][k][num]-180))
    # #                     data.append((gaitResults['curves_l']['mean'][k][num]-180))
    # #                 else:
    # #                     #print(gaitResults['curves_l']['mean'][k][num])
    # #                     data.append(gaitResults['curves_l']['mean'][k][num])
    # #             elif (k=='pelvis_list'):
    # #                 data.append(gaitResults['curves_l']['mean'][k][num]*-1)
    # #             else:
    # #                 #print(gaitResults['curves_l']['mean'][k][num])
    # #                 data.append(gaitResults['curves_l']['mean'][k][num])
                    
   
    # # # indiv_data=np.zeros([459,len(gaitResults['curves_r']['indiv'])+len(gaitResults['curves_l']['indiv'])])
   
    # # indiv_data=np.zeros([459,len(gaitResults['curves_r']['indiv'])])
    
    # # for rcou in range(0,len(gaitResults['curves_r']['indiv'])):
    # #     rowcou=0
    # #     for k in joint_names:
    # #         for num in range(101):
    # #             if (num % 2 ==0):
    # #                 if (k=='pelvis_tilt'):
    # #                     indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]+20
    # #                     rowcou+=1
    # #                 elif (k=='pelvis_rotation'):
    # #                     if(gaitResults['curves_r']['indiv'][rcou][k][num] > 180):
    # #                         indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-180
    # #                         rowcou+=1
    # #                     else:
    # #                         indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]
    # #                         rowcou+=1
    # #                 else:
    # #                     indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]
    # #                     rowcou+=1
                        
    # #     # np.append(indiv_data, temp_data)         
        
    # # np.savetxt(savpath + '/' + subjid + '-' + trial_name + '_right.csv', indiv_data, delimiter=',', fmt='%f')   
        
    # # for lcou in range(0,len(gaitResults['curves_l']['indiv'])):
    # #     rowcou=0
    # #     for k in joint_names2:
    # #         for num in range(101):
    # #             if (num % 2 ==0):
    # #                 if (k=='pelvis_tilt'):
    # #                     indiv_data[rowcou,rcou+lcou+1]=gaitResults['curves_l']['indiv'][lcou][k][num]+20
    # #                     rowcou+=1
    # #                 elif (k=='pelvis_rotation'):
    # #                     if(gaitResults['curves_l']['indiv'][lcou][k][num] > 180):
    # #                         indiv_data[rowcou,rcou+lcou+1]=gaitResults['curves_l']['indiv'][lcou][k][num]-180
    # #                         rowcou+=1
    # #                     else:
    # #                         indiv_data[rowcou,rcou+lcou+1]=gaitResults['curves_l']['indiv'][lcou][k][num]
    # #                         rowcou+=1
    # #                 else:
    # #                     indiv_data[rowcou,rcou+lcou+1]=gaitResults['curves_l']['indiv'][lcou][k][num]
    # #                     rowcou+=1
    #                 # indiv_data[rowcou,rcou+lcou+1]=(gaitResults['curves_l']['indiv'][lcou][k][num])
    #                 # rowcou+=1
                
    #     # np.append(indiv_data, temp_data)   
         
    # # np.savetxt('mat-dat-'+session_id+trial_name+'.csv',indiv_data, delimiter=',',fmt='%f')
    
    # indiv_data=np.zeros([459,len(gaitResults['curves_l']['indiv'])])
    
    # for lcou in range(0,len(gaitResults['curves_l']['indiv'])):
    #     rowcou=0
    #     for k in joint_names2:
    #         for num in range(101):
    #             if (num % 2 ==0):
    #                 if (k=='pelvis_tilt'):
    #                     indiv_data[rowcou,lcou]=gaitResults['curves_l']['indiv'][lcou][k][num]*-1+20
    #                     rowcou+=1
    #                 elif (k=='pelvis_rotation'):
    #                     if(gaitResults['curves_l']['indiv'][lcou][k][num] > 180):
    #                         indiv_data[rowcou,lcou]=gaitResults['curves_l']['indiv'][lcou][k][num]-180
    #                         rowcou+=1
    #                     else:
    #                         indiv_data[rowcou,lcou]=gaitResults['curves_l']['indiv'][lcou][k][num]
    #                         rowcou+=1
    #                 elif (k=='pelvis_list'):
    #                     indiv_data[rowcou,lcou]=gaitResults['curves_l']['indiv'][lcou][k][num]*-1
    #                     rowcou+=1
    #                 else:
    #                     indiv_data[rowcou,lcou]=gaitResults['curves_l']['indiv'][lcou][k][num]
    #                     rowcou+=1
    
    # np.savetxt(savpath + '/' + subjid + '-' + trial_name + '_left.csv', indiv_data, delimiter=',', fmt='%f')
    

    
    
    # data2=[]
    # reduceddat=[]
    # data3=[]
    
    # # reduceddat=np.concatenate((indiv_data[153:255],indiv_data[306:408]),axis=0)
    # # reduceddat=indiv_data[153::]
    # reduceddat=np.concatenate((indiv_data[153:255],indiv_data[306:459]),axis=0)
    # if np.size(reduceddat,1)>2:
    #     mediandat=np.median(reduceddat,1)
    #     numb=5
    #     n=len(reduceddat)
    #     tris=np.size(reduceddat,1)
    #     singlevariabledepth=np.zeros((numb,tris))
    #     starts=[0, 51, 102, 153, 204, 255]
    #     absmeddistance=np.zeros((n,tris))
    #     for i in range(tris):
    #         for j in range(numb):
    #             singlevariabledepth[j,i]=(sum(abs(reduceddat[starts[j]+1:starts[j+1]-2,i]
    #                                               -mediandat[starts[j]+1:starts[j+1]-2]))+abs(reduceddat[starts[j],i]
    #                                                 -mediandat[starts[j]])+abs(reduceddat[starts[j+1]-1,i]-mediandat[starts[j+1]-1])/2)/50;
        
    #     overalldepth=np.mean(singlevariabledepth,0)      
    #     c=np.argsort(overalldepth)
    #     ap=np.zeros((1,tris))
    #     features=np.size(matrix,0)
    #     rsco=ap
    #     for i in range(tris):
    #         ap[0,i]=abs(overalldepth[i]-np.median(overalldepth))
    #     medabdev=1.483*np.median(ap)
    #     for i in range(tris):
    #         rsco[0,i]=(overalldepth[i]-np.median(overalldepth))/medabdev
        
    #     data3=reduceddat[:,(abs(rsco)<3).flatten()]
    #     c2=c[(abs(rsco)<3).flatten()]
    #     if len(c2)>5:
    #         data2=reduceddat[:,(c<6).flatten()]
    #     else:
    #         data2=data3
    # else:
    #     data2=reduceddat
        
    # redtris=np.size(data2,1)
    # features=np.size(matrix,0)
    # subject=np.zeros([features,redtris])
    # diff=subject
    # value=data2
    
    # if msflag==0:
    #     # ans=data[153:255]+data[306:408]
    #     # print(np.array(ans))
    #     # value = np.array(ans)
    #     for i in range(redtris):
    #         # value[:,i]=data2[:,i]
    #         np.set_printoptions(suppress=True)
    #         subject[:,i]=np.matmul(matrix,value[:,i])
    #     # value=data2
    #     # np.set_printoptions(suppress=True)
    #     # subject = np.matmul(matrix, value)
    # else:
    #     for i in range(redtris):
    #         np.set_printoptions(suppress=True)
    #         subject[:,i]=np.matmul(matrix,value[:,i])
    #     # ans=data[153::]
    #     # value=np.array(ans)
    #     # np.set_printoptions(suppress=True)
    #     # subject=np.matmul(matrix,value)
    # # print(subject)
    # for i in range(redtris):
    #     diff[:,i]=subject[:,i]-controlCalc
    # # diff = subject - controlCalc
    # # print(diff)
    # msmean=3.64317
    # mssd=0.54211   
    # z_score=np.zeros(redtris)
    # GDI_l=np.zeros(redtris)
    # # ln_result = math.log(math.sqrt(np.sum(np.square(diff)) ))  # natural log of the euclidean distance between subjects and controls
    # # print(ln_result)
    # if sciflag==1:
    #     # z_score = (ln_result - 4.69)/.3 #The z-score is found by subtracting the average natural log accross all subjects to the ln_result and dividing by the SD of the average NL
    #     for i in range(redtris):
    #         ln_result = math.log(math.sqrt(np.sum(np.square(diff[:,i])) ))
    #         z_score[i] = (ln_result - 4.518094)/0.415455
    #         GDI_l[i]=100-(10*z_score[i])
    # elif msflag==1:
    #     # z_score = (ln_result - 4.15466)/0.44206
    #     # z_score = (ln_result - msmean)/mssd
    #     for i in range(redtris):
    #         ln_result = math.log(math.sqrt(np.sum(np.square(diff[:,i])) ))
    #         z_score[i] = (ln_result - msmean)/mssd
    #         GDI_l[i]=100-(10*z_score[i])
    # else:
    #     z_score = (ln_result - 4.69)/0.30
    # # print(z_score)
    # # GDI_r = 100 - (10*z_score)
    # print()
    # print("Left GDI: ")
    # if len(GDI_l)>1:
    #     print(GDI_l.mean())
    # else:
    #     print(GDI_l)

                
    # # # % Calculate the GDI
    # # if msflag==0:
    # #     ans=data[153:255]+data[306:408]
    # #     value = np.array(data)
    # #     subject = np.matmul(matrix, value)
    # # else:
    # #     ans=data[153::]
    # #     value=np.array(ans)
    # #     subject=np.matmul(matrix,value)
    
    # # diff = subject - controlCalc
    
    # # ln_result = math.log(math.sqrt(np.sum(np.square(diff)) ))  # natural log of the euclidean distance between subjects and controls
    # # if sciflag==1:
    # #     # z_score = (ln_result - 4.69)/0.3 #The z-score is found by subtracting the average natural log accross all subjects to the ln_result and dividing by the SD of the average NL
    # #     z_score = (ln_result - 4.911215)/.252333
    # # elif msflag==1:
    # #     # z_score = (ln_result - 4.44849)/0.39228
    # #     # z_score = (ln_result - 4.15466)/0.44206
    # #     z_score = (ln_result - msmean)/mssd
    # # else:
    # #     z_score = (ln_result - 4.69)/0.30
        
        
    # # GDI_l = 100 - (10*z_score)
    # # print()
    # # print("Left GDI: ")
    # # print(GDI_l)
    
    
    # #get the GDI average
    # # avg = (GDI_r + GDI_l)/2
    # # print()
    # # print("Average GDI: ")
    # # print(avg)
    # # print()
    
    # indiv_data=np.zeros([459,len(gaitResults['curves_r']['indiv'])+len(gaitResults['curves_l']['indiv'])])
   
      
    # for rcou in range(0,len(gaitResults['curves_r']['indiv'])):
    #     rowcou=0
    #     for k in joint_names:
    #         for num in range(101):
    #             if (num % 2 ==0):
    #                 if (k=='pelvis_tilt'):
    #                     indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]+20
    #                     rowcou+=1
    #                 elif (k=='pelvis_rotation'):
    #                     if(gaitResults['curves_r']['indiv'][rcou][k][num] > 180):
    #                         indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]-180
    #                         rowcou+=1
    #                     else:
    #                         indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]
    #                         rowcou+=1
    #                 else:
    #                     indiv_data[rowcou,rcou]=gaitResults['curves_r']['indiv'][rcou][k][num]
    #                     rowcou+=1
                        
    #     # np.append(indiv_data, temp_data)         
         
        
    # for lcou in range(0,len(gaitResults['curves_l']['indiv'])):
    #     rowcou=0
    #     for k in joint_names2:
    #         for num in range(101):
    #             if (num % 2 ==0):
    #                 if (k=='pelvis_tilt'):
    #                     indiv_data[rowcou,rcou+lcou+1]=gaitResults['curves_l']['indiv'][lcou][k][num]*-1+20
    #                     rowcou+=1
    #                 elif (k=='pelvis_rotation'):
    #                     if(gaitResults['curves_l']['indiv'][lcou][k][num] > 180):
    #                         indiv_data[rowcou,rcou+lcou+1]=gaitResults['curves_l']['indiv'][lcou][k][num]-180
    #                         rowcou+=1
    #                     else:
    #                         indiv_data[rowcou,rcou+lcou+1]=gaitResults['curves_l']['indiv'][lcou][k][num]
    #                         rowcou+=1
    #                 elif (k=='pelvis_list'):
    #                     indiv_data[rowcou,rcou+lcou+1]=gaitResults['curves_l']['indiv'][lcou][k][num]*-1
    #                     rowcou+=1
    #                 else:
    #                     indiv_data[rowcou,rcou+lcou+1]=gaitResults['curves_l']['indiv'][lcou][k][num]
    #                     rowcou+=1            
                        
    # np.savetxt(savpath + '/' + subjid + '-' + trial_name + '.csv', indiv_data, delimiter=',', fmt='%f')   
    
    
    # if len(GDI_r)>1:
    #     if len(GDI_l)>1:
    #         avg = (GDI_r.mean() + GDI_l.mean())/2
    #     else:
    #         avg = (GDI_r.mean() + GDI_l)/2
    # else:
    #     if len(GDI_l)>1:
    #         avg = (GDI_r + GDI_l.mean())/2
    #     else:
    #         avg = (GDI_r + GDI_l)/2
            
    # print()
    # print("Average GDI: ")
    # print(avg)
    # print()
    
    
    # print(gaitResults)
    # plot_dataframe_with_shading(
    #     [gaitResults['curves_r']['mean'], gaitResults['curves_l']['mean']],
    #     [gaitResults['curves_r']['sd'], gaitResults['curves_l']['sd']],
    #     leg = ['r', 'l'],
    #     xlabel= '% gait cycle',
    #     title= 'kinematics (m or deg)',
    #     legend_entries = ['right', 'left'])
    
    #ask user if they want to run another trial
    # response = input("Do you want to run another trial? [Y/N]: ").lower()
    
    # if response.lower() != 'y':
    #     break
    
