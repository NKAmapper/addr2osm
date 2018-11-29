# addr2osm

Compares addresses in OSM with latest address file from Kartverket for a given municipality and produces an osm update file

### Usage

1. Run `addr2osm <municipality id> [-manual]`
   * Use 4 digit Norwegian municipality codes
   * Will produce an OSM file with the name *Address import "code" "municipality".osm*
   * Add `-manual` for including copy of "surplus" address nodes, ways and relations not touched by the program + for including DELETE tag instead of deleting node for easier verification
  
2. Inspect the file in JOSM:
   * Searching: 
     - Modified address nodes: Search `-new modified`
     - New address nodes: Search `new`
     - Duplicate address nodes, ways, relations: Search `-new -modified`
     - Deleted address nodes: Search `DELETE` in manual mode, else visible in upload window only
     - Nodes which are part of other ways and relations: Search `modified -addr`
     
   * The duplicate addresses may be modified, deleted etc before upload
     - In manual mode please also remember to delete all nodes with DELETE tag before upload

3. Upload from JOSM to OSM
   * If no manual modifications have been done then OSM will be updated with the generated new, modified and deleted address nodes (only "pure" address nodes consisting of the 4 tags addr:street, addr:housenumber, addr:postcode and addr:city only)

### Notes

* Address nodes will be created if they do not currently exist in OSM, even if the address already is contained in e.g. a building or an amenity node
* Address nodes will be relocated according to the lates Kartverket coordinates, if necessary
* Remaining/not matched "pure" address nodes (without any other tags) will be reused (nearby location) or deleted
* The addr:country tag will be disregarded and removed
* The following elements will not be touched:
  - Ways and relations
  - Nodes containing other tags or incomplete address tags (not all 4 addr tags)
  - Nodes which are members of ways or relations (however complete address tags from those nodes will be moved to new address nodes)
* Code is optimized to near linear complexity with performance better than 1000 addresses/second in testing

### Data sources used

* [Kartverket SOSI municipality codes](https://register.geonorge.no/sosi-kodelister/kommunenummer)
* [Github addrnodeimport street name corrections](https://github.com/rubund/addrnodeimport/blob/master/xml/corrections.xml)
* [Kartverket street address files](https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenVegadresse/CSV/)
* [Overpass API](http://overpass-api.de)
