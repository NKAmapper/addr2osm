# addr2osm

Updates addresses in OSM for Norway and Sweden.

### Usage

1. Run `addr2osm <municipality/county id> [-upload]`
   * Parameter:
     - 4 digit municipality code, or
     - 2 digit county code for all municipalities within a county, or
     - "00" or "Sverige" for all municipalities in the country
   * Will produce OSM file with the name *address "code" "municipality".osm*, ncluding copy of "surplus" address nodes + for including *DELETE* tag for easier verification
   * Optional parameter:
     - `-upload` for uploading directly to OSM - will ask for OSM user name and password
     - `-source` for just producing file with addresses (no OSM data)

  
2. Inspect the file in JOSM:
   * Searching: 
     - Modified address nodes: Search `-new modified`
     - New address nodes: Search `new`
     - Duplicate address nodes, ways, relations: Search `-new -modified`
     - Deleted address nodes: Search `DELETE` in manual mode, else visible in upload window only
     - Nodes which are part of other ways and relations: Search `modified -addr`
     
   * The duplicate addresses may be modified, deleted etc before upload
     - In manual mode please also remember to delete all nodes with *DELETE* tag before upload

3. Upload from JOSM to OSM
   * If no manual modifications have been done then OSM will be updated with the generated new, modified and deleted address nodes (only "clean" address nodes consisting of the 4 tags *addr:street*, *addr:housenumber*, *addr:postcode* and *addr:city*, plus *addr:district* for Sweden).

### Notes

* Address nodes will be created if they do not currently exist in OSM.
* Address nodes will be relocated according to the lates source data coordinates, if necessary. The implication is that there is no need to move address nodes manually (they will be relocated during the next import update anyway).
* Remaining/not matched "pure" address nodes (without any other tags) will be reused (nearby location) or deleted.
* The *addr:country* tag will be disregarded and removed.
* Duplicated address tags on buildings and other objects will be removed unless the object is also tagged with a *note=** containing "*addr*".
* For Norway: Street names will be adjusted to get punctuation and spacing right. Errors in street names are also adjusted according to translation table in [addr2osm/corrections.json](https://github.com/NKAmapper/addr2osm/blob/master/corrections.json).
* Uploads to OSM are done as one changeset per county (alternatively per municipality). In case of errors the whole changeset will fail. If a county or municipality has more than 10.000 elements with changes it will have to be uploaded manually in JOSM.
* A separate file with all new and deleted addresses is saved. Useful for discovering buildings and higheways to be created or deleted.
* For Norway: A separate file with used address corrections is saved. Useful for updating the correction json file in Github every other year.

### Changelog ###

Sweden:
0.2:
  - Created version for Sweden.

Norway:
2.1:
  - Improved code for fixing street names.
  - Modify street name endings to lower case according to GitHub tabel, e.g. "Gate" -> "gate".
  - Replace closest unused existing addr node when street name is not matching.

2.0:
  - Python 3 support.
  - ElementTree implementation.
  - Upload by county (alternatively by municipality).
  - Improved handling of addr duplicates. Opt-out through note=* tag.
  - All new/deleted adresses saved in separate file (for reviewing new/deleted buildings or roads).
  - Used street name corrections logged to file.

### References ###

* [Sweden OSM import plan https://wiki.openstreetmap.org/wiki/Import/Catalogue/Sweden_Address_Import]
* [Lantmäteriet product page https://geotorget.lantmateriet.se/dokumentation/GEODOK/15/latest.html]
* [Norway OSM import plan https://wiki.openstreetmap.org/wiki/Import/Catalogue/Address_import_for_Norway]
* [Kartverket SOSI municipality codes](https://register.geonorge.no/sosi-kodelister/kommunenummer)
* [Kartverket street address files](https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenVegadresse/CSV/)
* [Overpass API](http://overpass-api.de)
* [addr2osm/corrections.json](https://github.com/NKAmapper/addr2osm/blob/master/corrections.json) - Street name corrections, based on [Github addrnodeimport street name corrections](https://github.com/rubund/addrnodeimport/blob/master/xml/corrections.xml)
