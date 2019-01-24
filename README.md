# addr2osm

Compares addresses in OSM with latest address file from Kartverket for a given municipality and either produces an OSM update file or uploads changes and additions directly to OSM.

### Usage

1. Run `addr2osm <municipality/county id> [-manual|-upload]`
   * Parameter:
     - 4 digit Norwegian municipality code, or
     - 2 digit county code for all municipalities within a county, or
     - "99" for all municipalities in Norway
   * Will produce OSM file with the name *Address import "code" "municipality".osm*
   * Optional parameters:
     - `-manual` for including copy of "surplus" address nodes, ways and relations not touched by the program + for including *DELETE* tag instead of deleting node for easier verification
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

* Address nodes will be created if they do not currently exist in OSM, even if the address already is contained in e.g. a building or an amenity node
* Address nodes will be relocated according to the lates Kartverket coordinates, if necessary
* Remaining/not matched "pure" address nodes (without any other tags) will be reused (nearby location) or deleted
* The *addr:country* tag will be disregarded and removed
* Address tags on buildings will be removed unless the building is also tagged with one of *amenity*, *leisure*, *tourism*, *shop*, *office*, *craft* and *club*
* The following elements will not be touched:
  - Ways and relations, except buildings as described above
  - Nodes containing other tags or incomplete address tags (not all 4 addr tags)
  - Nodes which are members of ways or relations (however complete address tags from those nodes will be moved to new address nodes)
* Street names are fixed when needed to get punctuation and spacing right. Errors in street names are also fixed according to translation table in [addr2osm/corrections.json](https://github.com/NKAmapper/addr2osm/blob/master/corrections.json).
* Code is optimized to near linear complexity with performance at 500-1500 addresses/second in testing (slower with "-manual")
* Uploads to OSM are done as one changeset per municipality. In case of errors the whole changeset will fail. If a municipality has more than 10.000 elements with changes it will have to be uploaded manually in JOSM.

### Data sources used

* [Kartverket SOSI municipality codes](https://register.geonorge.no/sosi-kodelister/kommunenummer)
* [Kartverket street address files](https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenVegadresse/CSV/)
* [Overpass API](http://overpass-api.de)
* [addr2osm/corrections.json](https://github.com/NKAmapper/addr2osm/blob/master/corrections.json) - Street name corrections, based on [Github addrnodeimport street name corrections](https://github.com/rubund/addrnodeimport/blob/master/xml/corrections.xml)
