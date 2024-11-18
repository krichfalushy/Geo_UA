"""
Завдання:
1. Знайти координати кордону України та занести їх у базу даних Oracle/PostgreSQL/MySQL.

2. Графічно відобразити кордон у середовищі Python або на веб-інтерфейсі за допомогою бібліотеки Leaflet.

3. Запропонувати алгоритм, який розбиватиме карту України на однакові квадрати (сторона ~1 км, можна і більше,
якщо не вистачає ресурсів на ноутбуці).

4. Зберегти вершини сформованих квадратів у базу даних Oracle/PostgreSQL/MySQL.

5. Графічно відобразити ці квадрати у середовищі Python на карті або на веб-інтерфейсі за допомогою бібліотеки Leaflet.

6. У вас є збережені координати вершин квадратів. З кожної вершини графічно зобразити 3 сектори з азимутами 0, 120 та
240 градусів, розкривши їх на 60 градусів радіусом 5 км. Запропонувати алгоритм, який обраховуватиме,
які вершини сформованих квадратів перетинає кожен сектор. Результати перетину зберегти в БД.

7. Графічно відобразити ці сектори поверх квадратів у середовищі Python на карті або на веб-інтерфейсі за допомогою бібліотеки Leaflet.

"""


import json
import mysql.connector
import folium
from shapely.geometry import box, shape, Point, Polygon
from shapely.affinity import rotate
import geopandas as gpd
import numpy as np


# my_db = mysql.connector.connect(
#     host="localhost",
#     user="root",
#     password="5687",
#     database="coordinates"
# )
#
# curs = my_db.cursor()
#
#
# file_json = r"/Users/admin/pythonProject1/projects/ukr_geo/ukr_border_coord.json"


def load_geos():
    curs.execute("""
            CREATE TABLE IF NOT EXISTS ukraine_geometry (
            id INT AUTO_INCREMENT PRIMARY KEY,
            country VARCHAR(255),
            geometry GEOMETRY NOT NULL);""")

    with open(file_json, "r", encoding="utf-8") as file:
        data = json.load(file)

    country_feature = data["features"][0]
    country_name = country_feature["properties"]["COUNTRY"]
    geometry = json.dumps(country_feature["geometry"])

    curs.execute("""
            INSERT INTO ukraine_geometry (country, geometry)
            VALUES (%s, ST_GeomFromGeoJSON(%s));
    """, (country_name, geometry))

    my_db.commit()


# world_map = folium.Map()
# world_map.save("test.html")

ukr_centre = [49.234420, 31.604797]


def outline_border():
    curs.execute("""SELECT ST_AsGeoJSON(geometry) FROM ukraine_geometry;""")
    borders = curs.fetchall()
    border_geojson = [json.loads(border[0]) for border in borders]

    ukr_border = folium.Map(
        location=ukr_centre,
        zoom_start=5
    )

    for border in border_geojson:
        folium.GeoJson(border).add_to(ukr_border)

    ukr_border.save("ukr_map.html")


# Алгоритм розбивки сітки
def create_grid(max_x, minx, maxy, miny, cell_size=0.01):
    grid = []
    x = minx
    while x < max_x:
        y = miny
        while y < maxy:
            grid.append(box(x, y, x + cell_size, y + cell_size))
            y += cell_size
        x += cell_size
    return grid


def load_grid(geo_file):
    curs.execute("""
            CREATE TABLE IF NOT EXISTS ukraine_grid (
            id INT AUTO_INCREMENT PRIMARY KEY,
            geometry GEOMETRY NOT NULL);""")

    with open(geo_file, "r", encoding="utf-8") as file:
        data = json.load(file)

    ukr_geo = None
    for feature in data["features"]:
        if feature["properties"]["COUNTRY"] == "Ukraine":
            ukr_geo = shape(feature["geometry"])
            break

    min_x, min_y, max_x, max_y = ukr_geo.bounds
    ukr_grid = create_grid(max_x, min_x, max_y, min_y)

    filtered_grid = [cell for cell in ukr_grid if cell.intersects(ukr_geo)]

    for cell in filtered_grid:
        curs.execute("""INSERT INTO ukraine_grid (geometry)
                        VALUES (ST_GeomFromText(%s));""", (cell.wkt,))

    # grid_gdf = gpd.GeoDataFrame(geometry=filtered_grid, crs="EPSG:4326")
    # return grid_gdf

    my_db.commit()


def outline_grid_geojson():
    grid_map = folium.Map(
        location=ukr_centre,
        zoom_start=5
    )

    folium.GeoJson("GRID", name="ukr_grid").add_to(grid_map)

    grid_map.save("ukr_grid.html")


def outline_grid_mysql():
    curs.execute("""SELECT ST_AsGeoJSON(geometry) FROM ukraine_grid;""")
    grids = curs.fetchall()

    grids_geojson = [json.loads(grid[0]) for grid in grids]

    grid_map = folium.Map(
        location=ukr_centre,
        zoom_start=5
    )

    for grid in grids_geojson:
        folium.GeoJson(grid).add_to(grid_map)

    grid_map.save("ukr_grids.html")


def create_sector(centre, radius, start_angle, end_angle, num_points=100):
    # Перевірка, щоб step не дорівнював 0
    step = max(1, int((end_angle - start_angle) / num_points))
    if step == 0:
        raise ValueError("Крок у range не може бути нульовим. Перевірте значення кутів і кількість точок.")

    angles = [np.radians(a) for a in range(start_angle, end_angle + 1, step)]
    points = [(centre.x + radius * np.cos(angle), centre.y + radius * np.sin(angle)) for angle in angles]
    points.insert(0, (centre.x, centre.y))
    return Polygon(points)


def process_sectors():
    curs.execute("""SELECT id, ST_AsText(geometry) FROM ukraine_grid;""")
    squares = curs.fetchall()

    query_sectors = """CREATE TABLE IF NOT EXISTS grid_sectors (
            id INT AUTO_INCREMENT PRIMARY KEY,
            square_id INT,
            sector_geometry GEOMETRY NOT NULL,
            FOREIGN KEY (square_id) REFERENCES ukraine_grid(id)
            );"""

    query_intersection = """CREATE TABLE IF NOT EXISTS sector_intersections (
            sector_id INT,
            intersected_square_id INT,
            FOREIGN KEY (sector_id) REFERENCES grid_sectors(id),
            FOREIGN KEY (intersected_square_id) REFERENCES ukraine_grid(id)
            );"""

    curs.execute(query_sectors)
    curs.execute(query_intersection)

    radius = 0.045   # 5 км у градусах

    for square_id, square_wkt in squares:
        square_geom = gpd.GeoSeries.from_wkt([square_wkt])[0]
        vertices = list(square_geom.exterior.coords)
        for vertex in vertices:
            centre = Point(vertex)

            for azimuth in [0, 120, 240]:
                sector = create_sector(centre, radius, azimuth - 30, azimuth + 30)

                query = """INSERT INTO grid_sectors (square_id, sector_geometry)
                        VALUES (%s, ST_GeomFromText(%s));"""
                curs.execute(query, (square_id, sector.wkt))

                sector_id = curs.lastrowid

                for other_square_id, other_square_wkt in squares:
                    other_square_geom = gpd.GeoSeries.from_wkt([other_square_wkt])[0]
                    if sector.intersects(other_square_geom):
                        curs.execute("""INSERT INTO sector_intersections (
                                sector_id, intersected_square_id) VALUES (%s, %s);""",
                                     (sector_id, other_square_id))

    my_db.commit()


def load_sectors():
    curs.execute("""SELECT id, ST_AsGeoJSON(geometry) FROM ukraine_grid;""")
    squares = curs.fetchall()

    curs.execute("""SELECT id, ST_AsGeoJSON(sector_geometry) FROM grid_sectors;""")
    sectors = curs.fetchall()

    sector_map = folium.Map(location=ukr_centre, zoom_start=5)

    for square_id, square_geojson in squares:
        square_geom = json.loads(square_geojson)
        folium.GeoJson(square_geom, style_function=lambda x: {"color": "blue", "weight": 1}).add_to(sector_map)

    for sector_id, sector_geojson in sectors:
        sector_geom = json.loads(sector_geojson)
        folium.GeoJson(sector_geom, style_function=lambda x: {"color": "red", "weight": 1}).add_to(sector_map)

    sector_map.save("sectors_and_squares.html")


# curs.close()
# my_db.close()


if __name__ == "__main__":
    file_json = r"/Users/admin/pythonProject1/projects/ukr_geo/ukr_border_coord.json"

    my_db = mysql.connector.connect(
      host="localhost",
      user=input(),
      password=input(),
      database="coordinates"
    )

    curs = my_db.cursor()

    # GRID = load_grid(file_json)
    # GRID.to_file("GRID", driver="GeoJSON")

    load_grid(file_json)
    outline_grid_geojson()
    outline_border()
    outline_grid_mysql()
    load_sectors()

    curs.close()
    my_db.close()

