#!/usr/bin/env python
# -*- coding: utf8

# ADDR2OSM.PY
# Loads addresses from Kartverket and creates an osm file with updates
# Usage: "python addr2osm.py <kommunenummer> [-manual]""
# Creates "new_addresses_xxxx_xxxxxx.osm" file
# Optional "-manual" parameter will add DELETE tag instead of deleting node + include surplus addr objects


import json
import urllib
import urllib2
import zipfile
import StringIO
import sys
import csv
import math
import time
from xml.etree import ElementTree
from itertools import tee


version = "0.2.0"


escape_characters = {
	'"': "&quot;",
	"'": "&apos;",
	"<": "&lt;",
	">": "&gt;"
}

# Escape string for osm xml file

def escape (value):

	value = value.replace("&", "&amp;")
	for change, to in escape_characters.iteritems():
		value = value.replace(change, to)
	return value


# Generate one osm tag

def osm_tag (key, value):

	global file_out

	value = value.strip()
	if value:
		value = escape(value).encode('utf-8')
		key = escape(key).encode('utf-8')
		file_out.write ("    <tag k='%s' v='%s' />\n" % (key, value))


# Generate one oms line

def osm_line (value):

	global file_out

	value = value.encode('utf-8')
	file_out.write (value)


# Output message

def message (output_text):

	sys.stdout.write (output_text)
	sys.stdout.flush()


# Search for and return osm child/member object in "recurse down" list from Overpass

def find_element (id_no):

	global osm_children

	for element in osm_children['elements']:
		if element['id'] == id_no:
			return element
	return None


# Output osm object to file with all tags and children/members from Overpass
# Parameter "action" is "delete", "modify", "new" or "output".

def osm_element (element, action):

	global osm_id
	global debug

	if action == "delete":
		if debug:
			action = ""
			element['tags']['DELETE'] = "yes"
		else:
			action = "action='delete' "
	elif action == "modify":
		action = "action='modify' "
	elif action == "output":
		action = ""

	if action == "new":
		osm_id -= 1
		osm_line ("  <node id='%i' action='modify' visible='true' lat='%f' lon='%f'>\n" % (osm_id, element['lat'], element['lon']))
	else:
		header = u"  <%s id='%i' %stimestamp='%s' uid='%i' user='%s' visible='true' version='%i' changeset='%i'"\
				% (element['type'], element['id'], action, element['timestamp'], element['uid'], element['user'],\
				element['version'], element['changeset'])
		if element['type'] == "node":
			header = header + " lat='%f' lon='%f'>\n" % (element['lat'], element['lon'])
		else:
			header = header + ">\n"
		osm_line (header)

	if "nodes" in element:
		for node in element['nodes']:
			osm_line ("    <nd ref='%i' />\n" % node)

	if "members" in element:
		for member in element['members']:
			osm_line ("    <member type='%s' ref='%i' role='%s' />\n" % (member['type'], member['ref'], member['role']))

	if "tags" in element:
		for key, value in element['tags'].iteritems():
			osm_tag (key, value)

	osm_line ("  </%s>\n" % element['type'])

	# Recursively output child/member objects if any

	if not(action):
		if "nodes" in element:
			for node in element['nodes']:
				osm_element (find_element(node), action="outut")

		if "members" in element:
			for member in element['members']:
				osm_element (find_element(member['ref']), action="output")


# Main program

if __name__ == '__main__':

	start_time = time.time()
	message ("\n-- addr2osm v%s --\n" % version)

	if (len(sys.argv) == 2) and (len(sys.argv[1]) == 4) and sys.argv[1].isdigit():
		municipality_id = sys.argv[1]
		debug = False
	elif (len(sys.argv) == 3) and (len(sys.argv[1]) == 4) and sys.argv[1].isdigit() and (sys.argv[2] == "-manual"):
		municipality_id = sys.argv[1]
		debug = True
	else:
		sys.exit ('Usage: Please type "python addr2osm.py <nnnn>" with 4 digit municipality number\n'\
					+ '       Add "-manual" to get surplus address objects and DELETE tag\n')

	# Load municipality id's and names from Kartverket code list

	message ("Loading municipality codes from Kartverket\n")
	file = urllib2.urlopen("https://register.geonorge.no/api/sosi-kodelister/kommunenummer.json?")
	municipality_data = json.load(file)
	file.close()

	municipality = {}
	for mun in municipality_data['containeditems']:
		if mun['status'] == "Gyldig":
			municipality[mun['codevalue']] = mun['label']

	# Find municipality name for given municipality number from program parameter

	if not(municipality_id in municipality):
		sys.exit ('Municipality number %s not found' % municipality_id)

	municipality_name = municipality[municipality_id].replace(u"Æ","A").replace(u"Ø","O").replace(u"Å","A")\
													.replace(u"æ","a").replace(u"ø","o").replace(u"å","a")
	length = municipality_name.find(" i ")
	if length >= 0:
		municipality_name = municipality_name[0:length]
	length = municipality_name.find(" - ")
	if length >= 0:
		municipality_name = municipality_name[length + 3:]

	# Load corrections from Github, skip the first 47 sami corrections

	message ("Loading street name corrections from Github rubund/addrnodeimport\n")
	filename = "https://raw.githubusercontent.com/rubund/addrnodeimport/master/xml/corrections.xml"
	file = urllib2.urlopen(filename)
	tree = ElementTree.parse(file)
	file.close()

	root = tree.getroot()
	corrections = {}
	i = 0
	for correction in root.findall('spelling'):
		i += 1
		if i > 47:  # Skip sami names
			corrections[correction.get('from').replace(u"’’","'")] = correction.get('to')

	# Load existing addr nodes in OSM for municipality, then recurse down to get any children/members

	message ("Loading existing addresses for %s %s from OSM... " % (municipality_id, municipality[municipality_id]))
	query = '[out:json][timeout:60];(area[ref=%s][admin_level=7];)->.a;(node["addr:street"](area.a););out center meta;' % (municipality_id)
	if debug:
		query = query.replace("node", "nwr")

	file = urllib2.urlopen("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query))
	osm_data = json.load(file)
	file.close()
	message ("%i" % len(osm_data['elements']))

	# Recurse up to get any parents

	query = query.replace("out center meta", "<;out meta")
	file = urllib2.urlopen("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query))
	osm_parents = json.load(file)
	file.close()

	parents = set()  # Will contain the id for children elements

	for element in osm_parents['elements']:
		if "nodes" in element:
			for node in element['nodes']:
				parents.add(node)

		if "members" in element:
			for member in element['members']:
				parents.add(member['ref'])

	message (" +%i parent objects" % len(osm_parents['elements']))
	osm_parents = None  # No longer needed

	if debug:
		query = query.replace("<;out meta", ">;out meta")
		file = urllib2.urlopen("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query))
		osm_children = json.load(file)
		file.close()
		message (" +%i child objects" % len(osm_children['elements']))
	else:
		osm_children = { 'elements': [] }

	message("\n")

	# Load latest address file for municipality from Kartverket

	filename = "Basisdata_%s_%s_4258_MatrikkelenVegadresse_CSV" % (municipality_id, municipality_name)
	message ("\nLoading address file %s from Kartverket\n" %filename)
	file_in = urllib2.urlopen("https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenVegadresse/CSV/" + filename + ".zip")
	zip_file = zipfile.ZipFile(StringIO.StringIO(file_in.read()))
	csv_file = zip_file.open(filename + "/matrikkelenVegadresse.csv")
	addr_table1, addr_table2 = tee(csv.DictReader(csv_file, delimiter=";"), 2)

	# Open outut file

	filename = "Address_import_%s_%s.osm" % (municipality_id, municipality_name)
	file_out = open(filename, "w")
	osm_line ("<?xml version='1.0' encoding='UTF-8'?>\n")
	osm_line ("<osm version='0.6' generator='addr2osm v%s' upload='false'>\n" % version)

	# Initiate loop

	osm_id = -1000
	corrected = 0
	added = 0
	modified = 0
	deleted = 0

	found = []  # Index list which Will contain True for matched adresses from Kartverket 

	message ('\rChecking addresses...')

	# Loop all addresses from Kartveret twice:
	# 1st pass: Find all 100% matches and remove from OSM list

	checked = -1

	for row in addr_table1:

		checked += 1
		found.append(False)

		if checked % 100 == 0:
			message ('\rChecking addresses... %i' % checked)

		if row['adressenavn']:

			latitude = float(row['Nord'])
			longitude = float(row['Øst'])

			street = row['adressenavn'].decode('utf-8')
			housenumber = row['nummer'] + row['bokstav'].decode('utf-8')
			postcode = row['postnummer']
			city = row['poststed'].decode('utf-8').title().replace(" I "," i ")

			if street in corrections:
				street = corrections[street]
				corrected += 1

			street = street.replace("'", u"’")
			found_index = -1

			# Loop existing addr objects from OSM to find first exact match of "pure" address node

			for osm_object in osm_data['elements']:
				found_index += 1

				tag = osm_object['tags']
				if (osm_object['type'] == "node") and (len(tag) == 4) and ('addr:housenumber' in tag) and ('addr:postcode' in tag) and ('addr:city' in tag):
					if (housenumber == tag['addr:housenumber']) and (street == tag['addr:street']) and (postcode == tag['addr:postcode'])\
						 and (city == tag['addr:city']):

						found[checked] = True
						distance = math.sqrt((osm_object['lat'] - latitude) ** 2 + (osm_object['lon'] - longitude) ** 2)

						# Modify object coordinates if it has been relocated. Keep the existing node if it has parents

						if distance > 0.00001:

							if osm_object['id'] in parents:
								modify_object = osm_object.copy()
								modify_object['tags'] = {}
								osm_element (modify_object, action="modify")  # Keep empty node if parents
								modified += 1

								osm_object['lat'] = latitude
								osm_object['lon'] = longitude
								osm_element (osm_object, action="new")  # Create new addr node
								added += 1

							else:
								osm_object['lat'] = latitude
								osm_object['lon'] = longitude
								osm_element (osm_object, action="modify")
								modified += 1

						del osm_data['elements'][found_index]  # Remove match to speed up looping
						break

	message ('\rChecking addresses... %i (%i corrected street names)\n' % (checked + 1, corrected))


	# 2nd pass: Find all remaining "pure" address nodes at same location which will be updated with new address information
	# "Pure" address node are nodes which contain all of addr:street, addr:housenumber, addr:postcode, addr:city and no other tags
	# Remaining non-matched addresses are output as new address nodes

	message ("\nCompleting file %s...\n" % filename)

	i = -1
	for row in addr_table2:
		i += 1

		if row['adressenavn']:

			if not(found[i]):

				latitude = float(row['Nord'])
				longitude = float(row['Øst'])

				street = row['adressenavn'].decode('utf-8')
				housenumber = row['nummer'] + row['bokstav'].decode('utf-8')
				postcode = row['postnummer']
				city = row['poststed'].decode('utf-8').title().replace(" I "," i ")

				if street in corrections:
					street = corrections[street]

				street = street.replace("'", u"’")
				found_index = -1
				modify = False

				# Loop existing addr objects to find first close match with "pure" address node, to be modified
				# Consider the match close if distance is less than 1/1000 degrees

				for osm_object in osm_data['elements']:
					found_index += 1
					if (len(osm_object['tags']) == 4) and (osm_object['type'] == "node"):

						distance = math.sqrt((osm_object['lat'] - latitude) ** 2 + (osm_object['lon'] - longitude) ** 2)

						if distance < 0.001:
							tag = osm_object['tags']
							if ('addr:housenumber' in tag) and ('addr:postcode' in tag) and ('addr:city' in tag):

								keep_object = osm_object.copy()
								del osm_data['elements'][found_index]
								modify = True
								break

				# Output new addr node to file if no match, or modified addr node if close location match
 
				if modify:
					modify_object = keep_object.copy()
				else:
					modify_object = {}
					modify_object['type'] = "node"
				
				modify_object['tags'] = {
					'addr:street': street,
					'addr:housenumber': housenumber,
					'addr:postcode': postcode,
					'addr:city': city					
				}

				modify_object["lat"] = latitude
				modify_object['lon'] = longitude

				if modify:

					if modify_object['id'] in parents:
						keep_object['tags'] = {}
						osm_element (keep_object, action="modify")  # Keeo empty node if parents
						modified += 1

						osm_element (modify_object, action="new")  # Create new addr node
						added += 1

					else:
						osm_element (modify_object, action="modify")
						modified += 1

				else:
					osm_element (modify_object, action="new")
					added += 1


	# Output copy of remaining, non-matched addr objects to file (candidates for manual deletion of address tags and potentially also addr nodes)
	# Delete remaining "pure" addr nodes (they got no match)

	for osm_object in osm_data['elements']:

		# Delete "pure" address node
		if (osm_object['type'] == "node") and (len(osm_object['tags']) == 4) and\
			('addr:housenumber' in osm_object['tags']) and ('addr:postcode' in osm_object['tags']) and ('addr:city' in osm_object['tags']):
			deleted += 1
			osm_element (osm_object, action="delete")
		elif debug:
			osm_element (osm_object, action="output")

	osm_line ("</osm>")

	# Wrap up and report

	file_in.close()
	file_out.close()

	message ('  New addresses:                            %i\n' % added)
	message ('  Updated existing address nodes:           %i\n' % modified)
	message ('  Deleted existing address nodes:           %i\n' % deleted)
	message ('  Remaining addresses in OSM without match: %i\n' % (len(osm_data['elements']) - deleted))

	time_spent = time.time() - start_time
	message ('\nTime %i seconds (%i addresses per second)\n\n' % (time_spent, checked / time_spent))
