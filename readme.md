# SMS Sahil

## Setup Instructions

### 1. Create and activate a virtual environment

```bash
python3 -m venv venv
# On Linux/macOS:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the application

```bash
python -m uvicorn main:app
```

### 4. Create a new admin user

After starting the server, open a new terminal and run:

```bash
python create_first_admin.py <username> <password> 1 1
```

Replace `<username>` and `<password>` with your desired credentials.


