import json

with open("historial_remoto.json") as f:
    remoto = set(json.load(f))

with open("historial.json") as f:
    local = set(json.load(f))

merged = list(remoto | local)[-500:]

with open("historial.json", "w") as f:
    json.dump(merged, f)

print("Historial fusionado: " + str(len(merged)) + " productos")
