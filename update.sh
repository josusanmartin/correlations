#!/bin/bash

# Activate virtual environment
source myenv/bin/activate

# Run Python script
python main.py

# Stage all changes for git commit
git add .

# Commit changes with a message
git commit -m "Update charts"

# Push changes to the remote repository
git push origin main
