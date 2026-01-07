# LuMo Motion Capture

## Repository Structure

### Core SDK and Official Files
- `LuMoSDKClient.py`: Official SDK client for LuMo motion capture system.
- `LusterFrameStruct_pb2.py`: Official protobuf communication definitions.
- `PythonSample.py`: Official example demonstrating SDK usage.

### Modified Samples
- ~~`SingleBodyPythonSample.py`~~: Legacy code based on `PythonSample.py` supporting post-hoc visualization of a rigid body after data collection (does **not** support marker data).  
  
  **Deprecated:** Please use `LuMoPythonSample.py` instead.
  
- ~~`MarkerPointPythonSample.py`~~: Legacy code based on `PythonSample.py` supporting marker data collection (does **not** support visualization).  
  
  **Deprecated:** Please use `LuMoPythonSample.py` instead.
  
- `LuMoPythonSample.py`: Enhanced sample combining post-hoc visualization for rigid bodies and marker data collection.

- `LuMo_ESP32_bridge.py`: All-in-one script, including `LuMoPythonSample.py`'s functionalities and the communication with ESP32.

### Utilities
- `CustomFunc.py`: Utility functions including CSV loading and plotting helpers.

### Visualization Scripts

- `visualization/mocap_single_body_states.py`: Visualize motion data for a single rigid body.  
  
  **Usage:** `python mocap_single_body_states.py -r <rigid_id>`
  
- `visualization/mocap_marker_trajectories.py`: Plot 3D trajectories for markers starting with a specified rigid body prefix.  
  
  **Usage:** `python mocap_marker_trajectories.py -r <rigid_id>`
  
- `visualization/mocap_wing_bending.py`: Plot 3D marker trajectories and 2D wing bending shapes during upstroke and downstroke (**default servo mounting angle = 50deg**) from motion capture data, colored by normalized timestamp.  
  
  **Usage:** `python mocap_wing_bending.py -r Rigid2` (default: middle cycle for flapping motion) / `python mocap_wing_contour.py -r Rigid2 -c 0` (first cycle)
  
  **Note that** you need to specify `file_path` and `marker_name_map` correctly to get the desired results. This code only works for visualizing the bending of the main rod (not for the full wing!).
  
  **E.g.:** `python visualization/mocap_wing_bending.py -r Rigid_WingLite_R_MainRod -c 1`
  
- `visualization/mocap_simplified_wing_surface.py`: Plot full wing 3D surfaces during one wingstroke.
  
  **Usage:** `python mocap_simplified_wing_surface.py -r Rigid2` (default: middle cycle for flapping motion) / `python mocap_simplified_wing_surface.py -r Rigid2 -c 0` (first cycle)
  
  **E.g.:** `python visualization/mocap_simplified_wing_surface.py -r Rigid_WingLite_R_FullWing`
  
- `visualization/mocap_full_wing_contour.py`: Plot a flapping wing stroke cycle for the full wing (front & hind wing) from motion capture CSV data.
  
  **Usage:** `python mocap_full_wing_contour.py -r Rigid2` (default: middle cycle for flapping motion) / `python mocap_full_wing_contour.py -r Rigid2 -c 0` (first cycle)
  
  **Note that** you need to specify `root_marker` and `hind_marker` correctly to get the desired results. You can use `visualization/test_show_unique_wing_markers.py` to tell which is which.
  
  **E.g.:** `python visualization/mocap_full_wing_contour.py -r Rigid_WingLite_R_FullWing`
  
- `visualization/mocap_3d_trajectories.py`: Visualize 3D flight trajectories for all data files stored under the `data/` folder (by default), supporting rigid body filtering via `-f` to isolate specific tracked objects (needs to modify the rigid body name in the code accordingly).
  
  **Usage:** `python mocap_3d_trajectories.py -d <path_to_data_folder> [--rigid_filter/-f]` 
  
  **E.g.:** `python visualization/mocap_3d_trajectories.py -d data20250522/lanjian_servo_airpulselite_selected_trajectories -f `
  
- `visualization/flight_core_data.py`: Visualize flight data collected from IMU sensors.

- `visualization/compare_sensors.py`: Compare Euler angles and linear velocities from MoCap and IMU data.  
  
  **Usage:** `python compare_sensors.py mocap.csv imu.csv` 
  
  **E.g.:** `python visualization/compare_sensors.py data/20250522_155136_motion_data.csv data/155136.csv`

---

**Note:** Please ensure your data files and dependencies are correctly set up before running the visualization scripts.
