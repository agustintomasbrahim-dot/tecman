"""Categorias de materiales/stock con su jerarquia.

Estructura:
    - nombre: nombre de la categoria padre
    - items: lista de sub-items (vacia si la categoria no tiene sub-items)
    - guia: dict opcional con archivo a descargar/mostrar; si archivo esta
      vacio se muestra como "proximamente".
"""

MATERIAL_CATEGORIAS = [
    {
        "nombre": "Luminaria",
        "items": [],
        # Guia visible al seleccionar Luminaria. Si "archivo" esta vacio o
        # None, se muestra como "proximamente" (deshabilitado).
        "guia": {"archivo": "LAMPARAS_BASICAS.docx", "titulo": "Ver guia de luminaria"},
        "items": [
            "Artefactos de embutir",
            "Artefactos de aplicar",
            "Tubos LED",
            "Zócalos",
            "Lámparas AR111",
            "Lámparas PAR30",
            "Lámparas globo",
            "Lámparas campana",
            "Lámparas HQI",
        ],
    },
    {
        "nombre": "Insumos de electricidad",
        "items": [
            "Termica",
            "Cables unipolares 2.5",
            "Cables unipolares 1.5",
            "Cables unipolares (Varios)",
            "Disyuntor",
            "Tomas simples",
            "Tomas dobles",
            "Cable canal",
            "Bandejas",
            "Garrafas R22",
            "Garrafa 410",
            "Garrafa Gas Map (para soldar caneria de aires)",
        ],
    },
    {"nombre": "Pinturas", "items": []},
    {
        "nombre": "Accesorios para pintar",
        "items": [
            "Pincel",
            "Cinta de papel",
            "Bolsa de trapo",
            "Aguarras",
            "Thinner",
            "Rodillo de pelo corto",
            "Rodillo de pelo largo",
        ],
    },
    {
        "nombre": "Cortinas de aires",
        "items": [
            "90cm Negra",
            "90cm Blanca",
            "1.20 Negra",
            "1.20 Blanca",
        ],
    },
    {"nombre": "Placas de Durlock", "items": []},
    {"nombre": "Masilla de Durlock", "items": []},
    {"nombre": "Cinta para Durlock", "items": []},
    {
        "nombre": "Reparacion de techos",
        "items": [
            "Membrana liquida",
            "Rollo de manta / venda",
        ],
    },
]
