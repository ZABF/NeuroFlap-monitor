import pandas as pd

def extract_mocap_data(file_path):
    # Read the CSV while avoiding parsing errors
    df = pd.read_csv(file_path, delimiter=",")  # Read as strings to prevent conversion issues

    # Identify header rows
    name_row = df.iloc[2]  # Fourth row (index 3) contains body names
    quantity_row = df.iloc[5]  # Sixth row (index 5) contains quantities
    attribute_row = df.iloc[6]  # Seventh row (index 6) contains attributes
    
    # Rigid bodies of interest
    target_bodies = {"Leftwing", "Rightwing"}
    
    # Desired quantities to extract
    desired_quantities = {"Rotation", "Position", "Speed", "AcceleratedSpeed", "Palstance", "AccPalstance"}

    # Find column indices corresponding to the target rigid bodies
    print(f"fasdfdsa::{name_row}")
    target_indices = [i for i, name in enumerate(name_row) if name in target_bodies]
    print(f"afsdfa:{target_indices}")

    # Filter columns based on desired quantities
    selected_columns = [
        i for i in target_indices if quantity_row[i] in desired_quantities
    ]
    
    # Create structured output
    extracted_data = {
        "columns": [name_row[i] + "_" + quantity_row[i] + "_" + attribute_row[i] for i in selected_columns],
        "data": df.iloc[7:, selected_columns].reset_index(drop=True)  # Data starts from row 8
    }

    return extracted_data

# Example usage
file_path = "mocap_data.csv"  # Update with your actual file path
mocap_data = extract_mocap_data(file_path)

# Convert to DataFrame for easier analysis
df_extracted = pd.DataFrame(mocap_data["data"], columns=mocap_data["columns"])

# Display the extracted DataFrame
print(df_extracted.head())
