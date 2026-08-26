from pathlib import Path
import ast
import re

source = Path('tecman/sucursales_data.py')
text = source.read_text()

m = re.search(r'SUCURSALES_INFO = \{\n(.*)\n\}\n?$', text, re.S)
if not m:
    raise SystemExit('SUCURSALES_INFO block not found')

body = '{\n' + m.group(1) + '\n}'
data = ast.literal_eval(body)

official = {
    '011': ('MV', 'Moov Moron'),
    '014': ('DX', 'Dexter Soleil'),
    '020': ('DX', 'Dexter Pompeya'),
    '023': ('DX', 'Dexter Moreno'),
    '028': ('DX', 'Dexter San Martin Peatonal'),
    '035': ('MV', 'Moov Merlo'),
    '036': ('DX', 'Dexter Flores'),
    '043': ('MV', 'Moov Terrazas de Mayo'),
    '049': ('MV', 'Moov Alto Avellaneda'),
    '051': ('DX', 'Dexter San Miguel'),
    '052': ('MV', 'Moov Lomas'),
    '053': ('DX', 'Dexter Unicenter'),
    '054': ('DX', 'Dexter Berazategui'),
    '058': ('DX', 'Dexter Plaza Oeste'),
    '065': ('DX', 'Dexter Quilmes Factory'),
    '076': ('MV', 'Moov Corner Cordoba'),
    '077': ('MV', 'Moov Lanus'),
    '078': ('DX', 'Dexter Cordoba'),
    '080': ('DX', 'Dexter Campana'),
    '082': ('DX', 'Dexter Zarate'),
    '083': ('DX', 'Dexter Solano'),
    '091': ('DX', 'Dexter Junin'),
    '092': ('DX', 'Dexter Tandil'),
    '102': ('MV', 'Moov Florida'),
    '111': ('DX', 'Dexter San Fernando'),
    '114': ('DX', 'Dexter Santa Fe'),
    '116': ('DX', 'Dexter SG San Nicolas'),
    '120': ('DX', 'Dexter Catamarca Peatonal'),
    '121': ('MV', 'Moov Abasto'),
    '123': ('DX', 'Dexter Ruta 20'),
    '124': ('DX', 'Dexter Cordoba'),
    '125': ('DX', 'Dexter Parque Brown'),
    '126': ('MV', 'Moov Salta'),
    '127': ('MV', 'Moov Alto Rosario'),
    '128': ('DX', 'Dexter Portal de los Andes'),
    '132': ('DX', 'Dexter Plaza Shopping'),
    '133': ('DX', 'Dexter Neuquen'),
    '134': ('SC', 'Stock Center Neuquen'),
    '139': ('DX', 'Dexter Salta'),
    '141': ('DX', 'Dexter Escobar'),
    '142': ('DX', 'Dexter Varela'),
    '145': ('MV', 'Moov Mendoza'),
    '146': ('DX', 'Dexter La Rioja'),
    '147': ('DX', 'Dexter Palmas del Pilar'),
    '148': ('MV', 'Moov San Martin'),
    '156': ('DX', 'Dexter SG Abasto'),
    '157': ('SC', 'Stock Center Portal San Martin'),
    '158': ('DX', 'Dexter La Rioja Centro'),
    '159': ('MV', 'Moov San Juan'),
    '160': ('DX', 'Dexter Trelew'),
    '165': ('MV', 'Moov Cabildo'),
    '166': ('MV', 'Moov Rosario Peatonal'),
    '167': ('DX', 'Dexter Lomas'),
    '170': ('DX', 'Dexter Caballito'),
    '171': ('SC', 'Stock Center San Miguel'),
    '172': ('DX', 'Dexter San Juan'),
    '173': ('SC', 'Stock Center Tucuman'),
    '176': ('SC', 'Stock Center Gral Paz'),
    '177': ('SC', 'Stock Center San Justo'),
    '178': ('DX', 'Dexter Shopping La Paz'),
    '183': ('DX', 'Dexter SG Floyco'),
    '184': ('DX', 'Dexter Cabildo y Juramento'),
    '185': ('SC', 'Stock Center Parque Brown'),
    '186': ('DX', 'Dexter Panamericana'),
    '187': ('SC', 'Stock Center Lomas Center'),
    '188': ('MV', 'Moov Quilmes'),
    '190': ('SC', 'Stock Center Soleil'),
    '191': ('DX', 'Dexter Tucuman'),
    '192': ('DX', 'Dexter Portal San Martin'),
    '193': ('SC', 'Stock Center Salta'),
    '194': ('SC', 'Stock Center Calchaqui'),
    '195': ('SC', 'Stock Center Gaona'),
    '196': ('DX', 'Dexter Pacheco'),
    '198': ('SC', 'Stock Center Monte Grande'),
    '199': ('SC', 'Stock Center Unicenter'),
    '200': ('MV', 'Moov Caballito'),
    '202': ('SC', 'Stock Center Magnolias'),
    '203': ('SC', 'Stock Center Cordoba'),
    '204': ('SC', 'Stock Center Terrazas de Mayo'),
    '205': ('DX', 'Dexter Alto Comahue'),
    '206': ('DX', 'Dexter Mendoza Centro'),
    '207': ('DX', 'Dexter San Luis'),
    '208': ('SC', 'Stock Center Panamericana'),
    '209': ('SC', 'Stock Center Leloir'),
    '210': ('MV', 'Moov Shopping La Paz'),
    '211': ('DX', 'Dexter Villa Luzuriaga'),
    '212': ('DX', 'Dexter Catamarca Plaza'),
    '213': ('DX', 'Dexter Congreso'),
    '214': ('MV', 'Moov San Fernando'),
    '215': ('MV', 'Moov Cordoba II'),
    '216': ('DX', 'Dexter Quilmes'),
    '217': ('DX', 'Dexter Bahia Bkanca'),
    '219': ('MV', 'Moov Unicenter'),
    '220': ('DX', 'Dexter Corrientes'),
    '221': ('MV', 'Moov Flores'),
    '222': ('DX', 'Dexter Moron'),
    '224': ('MV', 'Moov Resistencia'),
    '226': ('MV', 'Moov Santa Fe'),
    '228': ('MV', 'Moov Varela'),
    '229': ('DX', 'Dexter Santiago del Estero'),
    '230': ('MV', 'Moov Tucuman'),
    '231': ('MV', 'Moov Portal Neuquen'),
    '232': ('MV', 'Moov Moreno'),
    '233': ('DX', 'Dexter Cordoba 9 de Julio'),
    '234': ('MV', 'Moov Parque Brown'),
    '235': ('DX', 'Dexter Jujuy'),
    '236': ('MV', 'Moov Mendoza Plaza Shopping'),
    '237': ('DX', 'Dexter Shopping Portal Canning'),
    '238': ('DX', 'Dexter Alto avellaneda Suc 238'),
    '239': ('DX', 'Dexter MDQ Independencia'),
    '240': ('DX', 'Dexter MDQ Luro SUC 240'),
    '241': ('MV', 'Moov MDQ Luro Suc 241'),
}

for code, (marca, tienda) in official.items():
    if code in data:
        data[code]['marca'] = marca
        data[code]['tienda'] = tienda

lines = ['"""Datos de sucursales Grupo Dabra/Dexter - extraido del listado oficial"""', '', '# Proveedores habituales por sucursal (para retiro directo de materiales).', '# Si una sucursal no figura aca, se toma el listado general PROVEEDORES de app.py.', '# Agustin puede completar/ajustar esta lista segun las necesidades reales.', 'PROVEEDORES_SUCURSAL = {', '    # Ejemplo: "023": ["CEYH", "Martin Microglobal"],', '}', '', 'SUCURSALES_INFO = {']
for code in sorted(data):
    item = data[code]
    lines.append(f'    "{code}": {item},')
lines.append('}')
source.write_text('\n'.join(lines) + '\n')
print(len(official), len(data))
