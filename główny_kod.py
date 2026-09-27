from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeatureRequest,
    QgsDataSourceUri, QgsFeature, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsField, QgsVectorDataProvider
)
from qgis.utils import iface  # Zapewnia dostęp do iface w nowszych wersjach
from qgis.PyQt.QtCore import QVariant

# Słownik dostępnych warstw w WFS GDOŚ
TYPY_OBSZAROW = {
    "Rezerwaty przyrody": "GDOS:Rezerwaty",
    "Parki Narodowe": "GDOS:ParkiNarodowe",
    "Parki Krajobrazowe": "GDOS:ParkiKrajobrazowe",
    "Obszary Natura 2000 (Siedliskowe - PLH)": "GDOS:SpecjalneObszaryOchrony",
    "Obszary Natura 2000 (Ptasie - PLB)": "GDOS:ObszarySpecjalnejOchrony",
    "Obszary Chronionego Krajobrazu": "GDOS:ObszaryChronionegoKrajobrazu",
    "Użytki Ekologiczne": "GDOS:UzytkiEkologiczne",
    "Pomniki Przyrody": "GDOS:PomnikiPrzyrody"
}

podsumowanie_konfig = "none?crs=epsg:2180&field=Nazwa:string&field=Typ:string&field=Powierzchnia:double&field=Odleglosc:double"
podsumowanie = QgsVectorLayer(podsumowanie_konfig,"Podsumowanie","memory")

# 1 opcja na zmianę nazwy kolumny (na obiekcie klasy QgsVector Layer)
# podsumowanie.startEditing()
# podsumowanie.renameAttribute(2, "Powierzchnia [m]")
# podsumowanie.renameAttribute(3, "Odległość [m]")
# podsumowanie.commitChanges()

# 2 opcja na zmianę nazwy kolumny (na obiekcie klasy QgsVectorDataProvider)
podsumowanie_dane = podsumowanie.dataProvider()
podsumowanie_dane.renameAttributes({2: "Powierzchnia [m]",
                                    3: "Odległość [m]"})
podsumowanie.updateFields()

def pobierz_warstwy_wfs(nazwa_typu_wfs, zasieg, nazwa_czytelna):
    """
    Pobiera obiekty z WFS GDOŚ dla podanego typu obszaru chroniego i zasięgu BBOX.
    Zwraca i dodaje do projektu warstwę z obszarami.
    """
    # Budujemy połączenie przy użyciu dedykowanej klasy QGIS
    uri = QgsDataSourceUri()
    uri.setParam("url", "https://sdi.gdos.gov.pl/wfs")  # adres wfs
    uri.setParam("typename", nazwa_typu_wfs)
    uri.setParam("srsname", "EPSG:2180")  # układ współrzędnych
    uri.setParam("version", "auto")
    uri.setParam("restrictToRequestBBOX", "1")  # wybór BBOX

    # Łączymy się z serwerem
    print(f"Łączenie z serwerem WFS GDOŚ dla: {nazwa_czytelna}...")
    warstwa_wfs = QgsVectorLayer(uri.uri(False), "", "WFS")

    if not warstwa_wfs.isValid():
        print("Błąd: Nie udało się połączyć. Sprawdź czy serwer GDOŚ jest dostępny.")
        return None  # Przerwanie funkcji w razie błędu
    else:
        #
        # Tworzymy lokalną, "lekką" warstwę w pamięci RAM
        crs_auth = warstwa_wfs.crs().authid()
        warstwa_wynikowa = QgsVectorLayer(f"Polygon?crs={crs_auth}", f"{nazwa_czytelna} (Bufor)", "memory")
        dane_wynikowe = warstwa_wynikowa.dataProvider()

        # Kopiujemy strukturę tabeli
        dane_wynikowe.addAttributes(warstwa_wfs.fields())
        dane_wynikowe.addAttributes([
            QgsField("Powierzchnia [m]", QVariant.Double),
            QgsField("Dystans [m]", QVariant.Double)
        ])
        warstwa_wynikowa.updateFields()

        # 5. Tworzymy zapytanie przestrzenne (BBOX)
        zapytanie = QgsFeatureRequest().setFilterRect(zasieg)

        obiekty_do_skopiowania = []
        for obiekt_wfs in warstwa_wfs.getFeatures(zapytanie):
            nowy_obiekt = QgsFeature(warstwa_wynikowa.fields())
            nowy_obiekt.setGeometry(obiekt_wfs.geometry())

            pow = nowy_obiekt.geometry().area()
            dyst = QgsGeometry.distance(nowy_obiekt.geometry(),geometria_sklejona)

            nowy_obiekt.setAttributes(obiekt_wfs.attributes() + [pow, dyst])
            obiekty_do_skopiowania.append(nowy_obiekt)

            uzupelnij_podsumowanie(nowy_obiekt, typ, pow, dyst, podsumowanie)

        # 6. Zapisujemy pobrane obiekty do warstwy tymczasowej
        dane_wynikowe.addFeatures(obiekty_do_skopiowania)
        warstwa_wynikowa.updateExtents()
        QgsProject.instance().addMapLayer(warstwa_wynikowa)
        print(f"Pobrano {len(obiekty_do_skopiowania)} obiektów z GDOŚ dla {nazwa_czytelna}.")

        # Muszę zrobić jakąś tabelę z podsumowaniem, gdzie dla każdego typu będę dodawał
        # info z podanym typem, nazwą, powierzchnią i odległością. Będzie to dodawane na koniec w formie tabeli do QGISa po warstwach

        # przed pętlą zrobię pustą tabelę
        # w pętli zrobię pętle w której będę ją wypełniał
        # po pętli będę ją dodawał
        return warstwa_wynikowa

def uzupelnij_podsumowanie(obiekt, typ_obszaru, powierzchnia, dystans, tabela):

    wiersz = QgsFeature(tabela.fields())  # tworzy pusty wiersz ze strukturą kolumn
    wiersz.setAttributes([
        obiekt["nazwa"],                # 0: Nazwa
        typ_obszaru,                    # 1: Typ
        powierzchnia,                   # 2: Powierzchnia
        dystans                         # 3: Odległość
    ])
    tabela.dataProvider().addFeature(wiersz)  # wstrzykuje wiersz


# ==========================================
# GŁÓWNA CZĘŚĆ SKRYPTU
# ==========================================

# Dane wejściowe
warstwa_zrodlowa = iface.activeLayer()

# ZABEZPIECZENIE 1: Czy warstwa jest wybrana i poprawna?
if not warstwa_zrodlowa or not warstwa_zrodlowa.isValid():
    print("BŁĄD: Nie wybrano poprawnej warstwy wejściowej w panelu QGIS!")
else:
    # Transformacja CRS jeśli to nie jest EPSG:2180

    target_crs = QgsCoordinateReferenceSystem("EPSG:2180")
    source_crs = warstwa_zrodlowa.crs()

    # Przygotowujemy transformację
    transformacja = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())

    # Zmienna na nasz sklejony obszar roboczy (np. kilka działek ewidencyjnych naraz)
    geometria_sklejona = QgsGeometry()

    for obiekt in warstwa_zrodlowa.getFeatures():
        geom = obiekt.geometry()  # Wyciągamy geometrię (kształt)

        # Jeśli trzeba, przeliczamy TEN JEDEN KSZTAŁT do EPSG:2180 (funkcja transform zmienia w locie)
        if source_crs != target_crs:
            geom.transform(transformacja)

        # Sklejamy z pozostałymi w jeden wielki obiekt
        if geometria_sklejona.isEmpty():
            geometria_sklejona = geom
        else:
            geometria_sklejona = geometria_sklejona.combine(geom)

    # I teraz BBOX (zasięg) bierzemy po prostu z naszej nowej, połączonej geometrii!
    zasieg = geometria_sklejona.boundingBox()

    odleglosc = 1000  # bufor od BBOXa warstwy źródłowej (1 km)
    zasieg.grow(odleglosc)

    print(
        f"Zasięg zapytania EPSG:2180: X({zasieg.xMinimum():.2f} - {zasieg.xMaximum():.2f}), Y({zasieg.yMinimum():.2f} - {zasieg.yMaximum():.2f})")

    wybrane_typy = ["Rezerwaty przyrody"]  # Wybieramy po czytelnej nazwie
    wszystkie_pobrane_obiekty = {}

    for typ in wybrane_typy:
        print(f"Pobieranie: {typ}...")
        kod_wfs = TYPY_OBSZAROW[typ]  # odwołanie do słownika na początku

        obiekty = pobierz_warstwy_wfs(kod_wfs, zasieg, typ)
        if obiekty:
            wszystkie_pobrane_obiekty[typ] = obiekty

    if wszystkie_pobrane_obiekty:
        QgsProject.instance().addMapLayer(podsumowanie)
    else:
        if len(wybrane_typy) > 1:
            print(f"W podanym zakresie nie znaleziono obszarów o typach: {', '.join(wybrane_typy)}.")
        if len(wybrane_typy) == 1:
            print(f"W podanym zakresie nie znaleziono obszarów o typie: {wybrane_typy}.")

    print(f"Pobrano dane dla {len(wszystkie_pobrane_obiekty)} typów obszarów.")