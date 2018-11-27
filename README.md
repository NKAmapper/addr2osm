# addr2osm

Compares addresses in OSM with latest address file from Kartverket for a given municipality and produces an osm update file

### Usage

1. Run `addr2osm <municipality id>`
   * Use 4 digit Norwegian municipality codes
   * Will produce an OSM file with the name *Address import "code" "municipality".osm*
  
2. Inspect the file in JOSM:
   * Searching: 
     - Modified address nodes: Search `-new modified`
     - New address nodes: Search `new`
     - Duplicate address nodes, ways, relations: Search `-new -modified`
     - Deleted address nodes: Only visible in upload window
     
   * The duplicate addresses may be modified, deleted etc before upload

3. Upload from JOSM to OSM
   * If no manual modifications have been done then OSM will be updated with the generated new, modified and deleted address nodes (only "pure" address nodes consisting of the 4 tags addr:street, addr:housenumber, addr:postcode and addr:city only)


### Data sources used

* [Kartverket SOSI municipality codes](https://register.geonorge.no/sosi-kodelister/kommunenummer)
* [Github addrnodeimport street name corrections](https://github.com/rubund/addrnodeimport/blob/master/xml/corrections.xml)
* [Kartverket street address files](https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenVegadresse/CSV/)
* [Overpass API](http://overpass-api.de)
