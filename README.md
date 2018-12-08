# addr2osm

Compares addresses in OSM with latest address file from Kartverket for a given municipality and produces an osm update file

### Usage

1. Run `addr2osm <municipality/county id> [-manual]`
   * Parameter:
     - 4 digit Norwegian municipality code, or
     - 2 digit county code for all municipalities within a county, or
     - "99" for all municipalities in Norway
   * Will produce OSM file with the name *Address import "code" "municipality".osm*
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
* Street names are fixed when needed to get punctuation and spacing right. Errors in street names are fixed according to translation table in [addr2osm/corrections.json](https://github.com/NKAmapper/addr2osm/blob/master/corrections.json).
* Code is optimized to near linear complexity with performance at 500-1500 addresses/second in testing (slower with "-manual")
* The code will be expanded to upload automatically to OSM

### Test run

* OSM-filesfor all Norwegian municipalities are avilable [here](https://drive.google.com/open?id=1TzUggXrU0XP-TTxaXPsmRKSnMlR7622Y)
* The files contain changes that would have been done for a real update + copy of remaining/surplus nodes, ways and realations which contain addr-tags but did not get a match
* Objects which did get a clear address match and no other modifications are not included
* For inspection only - please do not upload to OSM
* Please see recommendations for searches above
* Summary table: [Excel sheet](https://drive.google.com/open?id=10oF3YECS39WRrXiO_pzE9sxVtxH8yVOx)

### Data sources used

* [Kartverket SOSI municipality codes](https://register.geonorge.no/sosi-kodelister/kommunenummer)
* [Kartverket street address files](https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenVegadresse/CSV/)
* [Overpass API](http://overpass-api.de)
* [addr2osm/corrections.json](https://github.com/NKAmapper/addr2osm/blob/master/corrections.json) - Street name corrections, based on [Github addrnodeimport street name corrections](https://github.com/rubund/addrnodeimport/blob/master/xml/corrections.xml)
