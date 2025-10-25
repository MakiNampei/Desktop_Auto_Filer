import os
import shutil
import json
from datetime import datetime

LOG_FILE = "relocation_log.json"

def move_files(file_paths, destination_folder):
    """Move given files to the destination folder and log their original locations."""
    if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)

    moved_files = []
    for file_path in file_paths:
        if not os.path.isfile(file_path):
            print(f"Skipping: {file_path} (not found)")
            continue

        file_name = os.path.basename(file_path)
        dest_path = os.path.join(destination_folder, file_name)

        shutil.move(file_path, dest_path)
        moved_files.append({
            "source": file_path,
            "destination": dest_path
        })
        print(f"Moved: {file_path} → {dest_path}")

    if moved_files:
        log_action(moved_files)
        print(f"\nLogged {len(moved_files)} moves. You can undo them later.")

def log_action(moved_files):
    """Save move actions to a JSON log file for undo tracking."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "moves": moved_files
    }

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            data = json.load(f)
    else:
        data = []

    data.append(log_entry)

    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=4)

def undo_last_action():
    """Undo the most recent file move batch."""
    if not os.path.exists(LOG_FILE):
        print("No log file found. Nothing to undo.")
        return

    with open(LOG_FILE, "r") as f:
        data = json.load(f)

    if not data:
        print("No recorded actions to undo.")
        return

    last_action = data.pop()  # remove the last recorded move
    moved_files = last_action["moves"]

    for item in moved_files:
        src = item["source"]
        dest = item["destination"]
        if os.path.exists(dest):
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.move(dest, src)
            print(f"Undid move: {dest} → {src}")
        else:
            print(f"Cannot undo: {dest} not found.")

    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=4)

    print("\nUndo completed for the last action.")

# Example usage:
if __name__ == "__main__":
    print("1. Move files")
    print("2. Undo last move")
    choice = input("Choose an option: ")

    if choice == "1":
        files = input("Enter file paths (comma separated): ").split(",")
        files = [f.strip() for f in files]
        dest = input("Enter destination folder: ").strip()
        move_files(files, dest)
    elif choice == "2":
        undo_last_action()
    else:
        print("Invalid choice.")
