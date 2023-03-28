# addr2osm

Compares addresses in OSM with latest address file from Kartverket for a given municipality and either produces an OSM update file or uploads changes and additions directly to OSM.

### Usage

1. Run `addr2osm <municipality/county id> [-upload]`
   * Parameter:
     - 4 digit Norwegian municipality code, or
     - 2 digit county code for all municipalities within a county, or
     - "00" for all municipalities in Norway
   * Will produce OSM file with the name *address import "code" "municipality".osm*, ncluding copy of "surplus" address nodes + for including *DELETE* tag for easier verification
   * Optional parameter:
     - `-upload` for uploading directly to OSM - will ask for OSM user name and password

  
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
   * If no manual modifications have been done then OSM will be updated with the generated new, modified and deleted address nodes (only "pure" address nodes consisting of the 4 tags *addr:street*, *addr:housenumber*, *addr:postcode* and *addr:city*)

### Notes

* Address nodes will be created if they do not currently exist in OSM.
* Address nodes will be relocated according to the lates Kartverket coordinates, if necessary. The implication is that there is no need to move address nodes manually (they will be relocated during the next import update anyway).
* Remaining/not matched "pure" address nodes (without any other tags) will be reused (nearby location) or deleted.
* The *addr:country* tag will be disregarded and removed.
* Duplicated address tags on buildings and other objects will be removed unless the object is also tagged with a *note=** containing "*addr*".
* Street names will be adjusted to get punctuation and spacing right. Errors in street names are also adjusted according to translation table in [addr2osm/corrections.json](https://github.com/NKAmapper/addr2osm/blob/master/corrections.json).
* Code is optimized to near linear complexity with performance at 500-1500 addresses/second in testing.
* Uploads to OSM are done as one changeset per county (alternatively per municipality). In case of errors the whole changeset will fail. If a county or municipality has more than 10.000 elements with changes it will have to be uploaded manually in JOSM.
* A separate file with all new and deleted addresses is saved. Useful for discovering buildings and higheways to be created or deleted.
* A separate file with used address corrections is saved. Useful for updating the correction json file in Github every other year.

### Data sources used

* [Kartverket SOSI municipality codes](https://register.geonorge.no/sosi-kodelister/kommunenummer)
* [Kartverket street address files](https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenVegadresse/CSV/)
* [Overpass API](http://overpass-api.de)
* [addr2osm/corrections.json](https://github.com/NKAmapper/addr2osm/blob/master/corrections.json) - Street name corrections, based on [Github addrnodeimport street name corrections](https://github.com/rubund/addrnodeimport/blob/master/xml/corrections.xml)
