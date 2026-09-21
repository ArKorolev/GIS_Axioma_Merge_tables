# --- Форматы входа ---
INPUT_FORMATS = {
    "tab":     (["tab"],             "TAB (*.tab)"),
    "mif":     (["mif"],             "MIF/MID (*.mif)"),
    "shp":     (["shp"],             "SHP (*.shp)"),
    "geojson": (["geojson", "json"], "GeoJSON (*.geojson, *.json)"),
    "gpkg":    (["gpkg"],            "GeoPackage (*.gpkg)"),
    "csv":     (["csv"],             "CSV (*.csv)"),
}

# --- Форматы выхода ---
OUTPUT_FORMATS = {
    "tab":     ("tab",     "MapInfo TAB (*.tab)",       "tab"),
    "shp":     ("shp",     "ESRI Shapefile (*.shp)",    "shp"),
    "mif":     ("mif",     "MapInfo MIF/MID (*.mif)",   "mif"),
    "geojson": ("geojson", "GeoJSON (*.geojson)",       "ogr"),
    "gpkg":    ("gpkg",    "GeoPackage (*.gpkg)",       "ogr"),
    "kml":     ("kml",     "KML (*.kml)",               "ogr"),
    "csv":     ("csv",     "CSV (*.csv)",                "csv"),
}

OUTPUT_FILTERS = ";;".join(f for _, f, _ in OUTPUT_FORMATS.values())

EXT_TO_OUTPUT_KEY = {}
for _key, (_ext_name, _, _) in OUTPUT_FORMATS.items():
    EXT_TO_OUTPUT_KEY[_ext_name.lower()] = _key

OGR_DRIVERS = {
    "geojson": "GeoJSON",
    "gpkg": "GPKG",
    "kml": "KML",
}

SCHEMA_UI_UPDATE_INTERVAL = 10

OUTPUT_COMPANION_EXTS = {
    "tab": [".tab", ".dat", ".map", ".id", ".ind"],
    "shp": [".shp", ".dbf", ".shx", ".prj", ".cpg"],
    "mif": [".mif", ".mid"],
    "geojson": [".geojson"],
    "gpkg": [".gpkg"],
    "kml": [".kml"],
    "csv": [".csv"],
}

OGR_CREATE_DATA_KEYS = ['driver', 'ogr_driver', 'format', 'driver_name', 'GDAL_DRIVER_NAME']

WGS84_FORMATS = ("geojson", "kml")

GEOJSON_SCHEMA_BUFFER = 262144
