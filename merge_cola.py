# Fusiona cola local con cola remota evitando conflictos de git
# Mantiene el orden: primero los de la cola local (ya procesados parcialmente),
# luego los remotos que no estén ya en la local

with open("cola.txt") as f:
    local = [l.strip() for l in f if l.strip() and not l.startswith("#")]

with open("cola_remota.txt") as f:
    remota = [l.strip() for l in f if l.strip() and not l.startswith("#")]

# La cola local es la que manda (ya se publicaron los primeros MAX_POSTS)
# Solo añadir de la remota URLs que no estén ya en la local
local_set = set(local)
for url in remota:
    if url not in local_set:
        local.append(url)
        local_set.add(url)

with open("cola.txt", "w") as f:
    f.write("\n".join(local) + ("\n" if local else ""))

print("Cola fusionada: " + str(len(local)) + " URLs restantes")
