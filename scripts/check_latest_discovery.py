import json

with open('../scratch/discovery-40645488296.log') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            phase = data.get('phase', '?')
            if phase == 'HYDRATION_WINDOW':
                print('HYDRATION_WINDOW:', json.dumps(data, indent=2))
        except:
            pass