# -*- coding: utf-8 -*-
"""
Created on Wed Jul 15 15:12:40 2026

@author: abarry
"""

import opensim as osim
import os
import numpy as np
from math import degrees

def write_numpy_to_trc(file_path, markers_data, marker_names, frame_rate=100.0):
    """
    Writes 3D numpy marker data to a TRC file.
    
    :param file_path: Path to the .trc output file
    :param markers_data: NumPy array of shape (Frames, NumberOfMarkers, 3)
    :param marker_names: List of strings matching the marker names
    :param frame_rate: Camera frame rate (e.g., 100.0 Hz)
    """
    num_frames, coords, num_markers= markers_data.shape
    if coords != 3:
        raise ValueError("Last dimension must be 3 (x, y, z coordinates).")
    
    # Create the TRC header
    with open(file_path, 'w') as f:
        # Line 1: Header tags
        f.write("PathFileType  4\t(X/Y/Z)\t" + os.path.basename(file_path) + "\n")
        
        # Line 2: Metadata (DataRate, CameraRate, NumFrames, NumMarkers)
        f.write("DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames\n")
        f.write(f"{frame_rate}\t{frame_rate}\t{num_frames}\t{num_markers}\tm\t{frame_rate}\t1\t{num_frames}\n")
        
        # Line 3: Column Labels (Frame#, Time, Marker1_X, Marker1_Y, Marker1_Z, ...)
        f.write("Frame#\tTime")
        for name in marker_names:
            f.write(f"\t{name}\t\t")
        f.write("\n")
        
        # Line 4: Sub-labels (must be blank for X, Y, Z)
        f.write("\t")
        for i in range(num_markers):
            f.write(f"\tX{i+1}\tY{i+1}\tZ{i+1}")
        f.write("\n\n")  # Extra newline before data begins
        
        # Line 5+: The marker data table
        time_step = 1.0 / frame_rate
        for frame in range(num_frames):
            time = frame * time_step
            row_data = [f"{frame}", f"{time:.6f}"]
            
            for marker in range(num_markers):
                x = markers_data[frame, 0, marker]
                y = markers_data[frame, 1, marker]
                z = markers_data[frame, 2, marker]
                row_data.extend([f"{x:.6f}", f"{y:.6f}", f"{z:.6f}"])
            
            f.write("\t".join(row_data) + "\n")

osim.Logger.setLevel(5)
for i in range(10):
    motionPath=r"X:\Alex\UCM Analysis\data\OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3\OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3_bdfa7c28-db47-440d-b849-dd308e3e610c\OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3\OpenSimData\Kinematics"+r"\test"+str(i+1)+".mot"
     
    print(motionPath)       
    # motionPath=r"X:\Alex\UCM Analysis\data\old\OpenCapData_eaf3fac0Old\OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3\OpenSimData\Kinematics\test1.mot"
    # motionPath=r"X:\Alex\UCM Analysis\data\old\OpenCapData_eaf3fac0Old\OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3\MarkerData\IK_test1.mot"
    trcPath=motionPath[:-4]+".trc"
    #assign model
    arm=osim.Model(r"X:\Alex\UCM Analysis\data\OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3\OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3_bdfa7c28-db47-440d-b849-dd308e3e610c\OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3\OpenSimData\Model\LaiUhlrich2022_scaled.osim")
    
    # arm=osim.Model(r"X:\Alex\UCM Analysis\data\old\OpenCapData_eaf3fac0Old\OpenCapData_eaf3fac0-9052-4f15-a291-2d37e73461a3\OpenSimData\Model\LaiUhlrich2022_scaled.osim")
    
    jointNames=['pelvis_tilt','pelvis_list','pelvis_rotation','pelvis_tx','pelvis_ty','pelvis_tz','hip_flexion_r','hip_adduction_r',
                'hip_rotation_r','knee_angle_r','ankle_angle_r','subtalar_angle_r','mtp_angle_r','hip_flexion_l','hip_adduction_l','hip_rotation_l',
                'knee_angle_l','ankle_angle_l','subtalar_angle_l','mtp_angle_l','lumbar_extension','lumbar_bending','lumbar_rotation',
                'arm_flex_r','arm_add_r','arm_rot_r','elbow_flex_r'	,'pro_sup_r','arm_flex_l','arm_add_l','arm_rot_l','elbow_flex_l','pro_sup_l']
    
    # arm.setUseVisualizer(True)
    #need to initialize system as 0 state before running
    state=arm.initSystem()
    
    #getting number of muscles by getting size of muscle matrix
    Nmuscle=arm.getForceSet().getMuscles().getSize()
    
    #looping through muscles to turn off the muscle dynamics
    #This is necessary, otherwise opensim tries to solve the muscles which fails
    for i in range (Nmuscle):
            imusc=arm.getForceSet().getMuscles().get(i).getName()
            nmusc=arm.getForceSet().getMuscles().get(imusc)
            nmusc.set_ignore_activation_dynamics(True)
            nmusc.set_ignore_tendon_compliance(True)
            # musccomp=osim.DecorativeGeometry.safeDownCast(nmusc)
            # musccomp.hide()
    
    markerNum=arm.getMarkerSet().getSize()
    
    # viz=arm.getVisualizer().updSimbodyVisualizer()
    # viz.setDesiredFrameRate(60)
    # viz.setShowFrameRate(False)
    # arm.getVisualizer().show(state)
    
    marks=[]
    markName=[]
    pelvPos=[0,0,0]
    for i in range(markerNum):
        marks.append(arm.getMarkerSet().get(i))
        markName.append(arm.getMarkerSet().get(i).getName())
    state=arm.initSystem()       
    analyze=osim.AnalyzeTool(arm)
    analyze.setName('analyze')
    analyze.setCoordinatesFileName(motionPath)
    analyze.loadStatesFromFile(state)
    analyze.run()
    q=osim.TimeSeriesTable(motionPath)
    time=q.getIndependentColumn()
    directionNeck=np.zeros((len(time),3,markerNum))
    pelv=arm.getBodySet().get('pelvis')
    state=arm.initSystem()
    
    # arm.getVisualizer().show(state)
        
    for i,ii in enumerate(time):
        value=osim.RowVector(q.getRowAtIndex(i));
        rowSkip=0
        for j, coordinate in enumerate(arm.updCoordinateSet()):
            if j<36:
                if coordinate.getName().find('beta')!=-1:
                    coordinate.setValue(state,0,False)
                    rowSkip+=1
                else:    
                    coordinate.setValue(state,np.radians(value[j-rowSkip]),False)
        arm.realizePosition(state)
        for k in range(markerNum):
            r=marks[k].getLocationInGround(state).to_numpy()
            directionNeck[i,0:3,k]=([float(r[0])+value[3],float(r[1])+value[4],float(r[2])])
        # arm.getVisualizer().show(state)
            
            
    write_numpy_to_trc(trcPath, directionNeck, markName, 60.0)
    
    ikMot=trcPath[:-4]+"_ik.mot"
    state=arm.initSystem()
    ik=osim.InverseKinematicsTool()
    ik.setModel(arm)
    ik.setMarkerDataFileName(trcPath)
    ik.setOutputMotionFileName(ikMot)
    ik.setEndTime(time[-1])
    ik.run()
    