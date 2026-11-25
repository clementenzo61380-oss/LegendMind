extends Node
## Simulation d'UNE région côté serveur (monstres, apparitions, règles).
## Vide pour l'instant : c'est la « boîte » dans laquelle on rangera tout
## ce qui concerne une région, pour pouvoir la déplacer un jour sur sa
## propre machine.

var region_id: String = ""


func _ready() -> void:
	print("[Serveur] Région prête : %s" % region_id)
