#!/usr/bin/env python
# -*- coding: utf8

# ADDR2OSM.PY
# Loads addresses from Kartverket and creates an osm file with updates
# Usage: "python addr2osm.py <kommune/fylkesnummer> [-manual]""
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
from itertools import tee


version = "0.5.1"
request_header = {"User-Agent": "addr2osm/" + version}


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

	value = value.strip()
	if value:
		value = escape(value).encode('utf-8')
		key = escape(key).encode('utf-8')
		file_out.write ("    <tag k='%s' v='%s' />\n" % (key, value))


# Generate one oms line

def osm_line (value):

	value = value.encode('utf-8')
	file_out.write (value)


# Open file/api, try up to 5 times

def open_url (url):

	tries = 1
	while tries < 5:
		tries += 1
		try:
			return urllib2.urlopen(url)
		except urllib2.HTTPError, e:
			if e.code == 429:
				time.sleep(5)
	raise


# Output message

def message (output_text):

	sys.stdout.write (output_text)
	sys.stdout.flush()


# Write to log file

def log (*args, **kwargs):

	global file_log

	if ("action" in kwargs) and (kwargs['action'] == "open"):
		filename = time.strftime("log_addr2osm_%d%b%Y_%H.%M.csv", time.localtime())
		file_log = open(filename, "w")
		output_text = "County;County name;Municipality;Municipality name;"\
						+ "OSM addresses;OSM parents;OSM children;Kartverket addresses;Kartverket street names;"\
						+ "Full match;Not full match;Corrected street names;New;Updated;Deleted;Remaining;Time\n"
		file_log.write (output_text)
	elif ("action" in kwargs) and (kwargs['action'] == "close"):
		file_log.close()
	else:
		for data in args:
			if type(data) == unicode:
				file_log.write(data.encode('utf-8'))
			else:
				file_log.write(str(data))
			if not(("action" in kwargs) and (kwargs['action'] == "end_line")):
				file_log.write(";")
		if ("action" in kwargs) and (kwargs['action'] == "endline"):
				file_log.write("\n")



# Search for and return osm child/member object in "recurse down" list from Overpass

def find_element (id_no):

	for element in osm_children['elements']:
		if element['id'] == id_no:
			return element
	return None


# Key for sorting osm objects

def addr_sort (element):

	if "addr:street" in element['tags']:
		return element['tags']['addr:street']
	else:
		return u"ÅÅÅ"


# Fix street name initials/dots and spacing. Return also True if anything changed

# Dr.Gregertsens vei -> Dr. Gregertsens vei
# Arne M Holdens vei -> Arne M. Holdens vei
# O G Hauges veg -> O.G. Hauges veg
# C. A. Pihls gate -> C.A. Pihls gate

def fix_street_name (name):

	# First test exceptions

	if name in corrections:
		return (corrections[name], True)

	# Loop characters in street name and make automatic corrections for dots and spacing

	new_name = ""
	length = len(name)

	i = 0
	word = 0  # Length of last word while looping street name

	while i < length - 3:  # Avoid last 3 characters to enable forward looking tests

		if name[i] == ".":
			if (name[i + 1] == " ") and (name[i + 3] in ["."," "]):  # C. A. Pihls gate
				new_name = new_name + "." + name[i + 2]
				i += 2
				word = 1
			elif name[i + 1] != " " and not(name[i + 2] in ["."," "]):  # Dr.Gregertsens vei
				new_name = new_name + ". "
				word = 0
			else:
				new_name = new_name + "."
				word = 0

		elif name[i] == " ":
			if  word == 1:
				if name[i + 2] in [" ","."]:  # O G Hauges veg
					new_name = new_name + "."
				else:
					new_name = new_name + ". "  # K Sundts vei
			else:
				new_name = new_name + " "
			word = 0

		else:
			new_name = new_name + name[i]
			word += 1

		i += 1

	new_name = new_name + name[i:i + 3]

	if name != new_name:
		return (new_name, True)
	else:
		return (name, False)


# Output osm object to file with all tags and children/members from Overpass
# Parameter "action" is "delete", "modify", "new" or "output".

def osm_element (element, action):

	global osm_id

	if element:  # None if recurse down more than 1 level

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
					% (element['type'], element['id'], action, element['timestamp'], element['uid'], escape(element['user']),\
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
				osm_line ("    <member type='%s' ref='%i' role='%s' />\n" % (escape(member['type']), member['ref'], member['role']))

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


# Process one municipality

def process_municipality (municipality_id):

	global file_out
	global osm_id
	global osm_children

	start_time = time.time()

	# Find municipality name for given municipality number from program parameter

	municipality_name = municipality[municipality_id].replace(u"Æ","E").replace(u"Ø","O").replace(u"Å","A")\
													.replace(u"æ","e").replace(u"ø","o").replace(u"å","a")
	length = municipality_name.find(" i ")
	if length >= 0:
		municipality_name = municipality_name[0:length]
	length = municipality_name.find(" - ")
	if length >= 0:
		municipality_name = municipality_name[length + 3:]
	if municipality_id == "1940":
		municipality_name = "Gaivuotna"

	log (municipality_id[0:2], county[municipality_id[0:2]], municipality_id, municipality[municipality_id])

	# Load existing addr nodes in OSM for municipality

	message ("\nLoading existing addresses for %s %s from OSM Overpass... " % (municipality_id, municipality[municipality_id]))
	query = '[out:json][timeout:60];(area[ref=%s][admin_level=7][place=municipality];)->.a;(node["addr:street"](area.a););out center meta;'\
			 % (municipality_id)
	if debug:
		query = query.replace('node["addr:street"]', 'nwr[~"addr:"~".*"]')  # Any addr tag

	request = urllib2.Request("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query), headers=request_header)
	file = open_url(request)
	osm_data = json.load(file)
	file.close()

	# Sort list and make index to speed up matching. Also set flag if "pure" address node

	street_index = dict()

	if osm_data['elements']:

		osm_data['elements'].sort(key=addr_sort)
		if "addr:street" in osm_data['elements'][0]['tags']:
			last_street = osm_data['elements'][0]['tags']['addr:street']
			street_index[last_street] = {'from': 0, 'to': 0}
		else:
			last_street = None

		i = -1
		for element in osm_data['elements']:
			i += 1
			tag = element['tags']

			if "addr:street" in element['tags']:
				this_street = element['tags']['addr:street']
				if this_street != last_street:
					street_index[last_street]['to'] = i - 1
					street_index[this_street] = {'from': i, 'to': 0}
					last_street = this_street

			# Flag if "pure" address node for improved speed later
			if element['type'] == "node" and ('addr:housenumber' in tag) and ('addr:postcode' in tag) and ('addr:city' in tag)\
				and ((len(tag) == 4) or ((len(tag) == 5) and ('addr:country' in tag))) :
				element['pure'] = True
			else:
				element['pure'] = False

		if last_street:
			street_index[last_street]['to'] = i

	message ("%i" % (len(osm_data['elements'])))
	log (len(osm_data['elements']))

	# Recurse up to get any parents

	query = query.replace("out center meta", "<;out meta")
	request = urllib2.Request("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query), headers=request_header)
	file = open_url(request)
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

	message (" +%i parent objects" % (len(osm_parents['elements'])))
	log (len(osm_parents['elements']))
	osm_parents = None  # No longer needed

	if debug:
		query = query.replace("<;out meta", ">;out meta")
		request = urllib2.Request("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query), headers=request_header)
		file = open_url(request)
		osm_children = json.load(file)
		file.close()
		message (" +%i child objects" % (len(osm_children['elements'])))
	else:
		osm_children = { 'elements': [] }

	log (len(osm_children['elements']))

	# Load latest address file for municipality from Kartverket

	filename = "Basisdata_%s_%s_4258_MatrikkelenVegadresse_CSV" % (municipality_id, municipality_name)
	filename = filename.replace(" ", "_")
	message ("\nLoading address file %s from Kartverket\n" % filename)
	file_in = open_url("https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenVegadresse/CSV/" + filename + ".zip")
	zip_file = zipfile.ZipFile(StringIO.StringIO(file_in.read()))
	csv_file = zip_file.open(filename + "/matrikkelenVegadresse.csv")
	addr_table1, addr_table2 = tee(csv.DictReader(csv_file, delimiter=";"), 2)

	# Open outut file

	filename = "Address_import_%s_%s.osm" % (municipality_id, municipality_name)
	filename = filename.replace(" ", "_")
	file_out = open(filename, "w")
	osm_line ("<?xml version='1.0' encoding='UTF-8'?>\n")
	osm_line ("<osm version='0.6' generator='addr2osm v%s' upload='false'>\n" % version)

	# Initiate loop

	osm_id = -1000
	matched = 0
	corrected = 0
	added = 0
	modified = 0
	deleted = 0
	validated = 0

	found = []  # Index list which Will contain True for matched adresses from Kartverket 

	message ('\nChecking addresses...')

	# 1st pass:
	# Find all 100% matches betweem Kartverket and OSM

	checked = -1

	for row in addr_table1:

		checked += 1
		found.append(False)

		if (checked + 1) % 1000 == 0:
				message ('\rChecking addresses... %i' % (checked + 1))

		if row['adressenavn']:

			validated += 1

			latitude = float(row['Nord'])
			longitude = float(row['Øst'])

			street = row['adressenavn'].decode('utf-8')
			housenumber = row['nummer'] + row['bokstav'].decode('utf-8')
			postcode = row['postnummer']
			city = row['poststed'].decode('utf-8').title().replace(" I "," i ")

			street, any_change = fix_street_name(street) 
			if any_change:
				corrected += 1

			if not(street in street_index):
				continue

			found_index = street_index[street]['from'] - 1

			# Loop existing addr objects from OSM to find first exact match of "pure" address node

			for osm_object in osm_data['elements'][ street_index[street]['from'] : street_index[street]['to'] + 1 ]:
				found_index += 1
				tag = osm_object['tags']

				if (osm_object['pure']) and (housenumber == tag['addr:housenumber']) and (street == tag['addr:street'])\
					 and (postcode == tag['addr:postcode']) and (city == tag['addr:city']):

					found[checked] = True
					matched += 1
					distance = math.sqrt((osm_object['lat'] - latitude) ** 2 + (osm_object['lon'] - longitude) ** 2)

					# Modify object coordinates if it has been relocated. Keep the existing node if it has parents

					if (distance > 0.00001) or ('addr:country' in tag):

						if osm_object['id'] in parents:
							modify_object = osm_object.copy()
							modify_object['tags'] = {}
							osm_element (modify_object, action="modify")  # Keep empty node if parents
							modified += 1

							osm_object['lat'] = latitude
							osm_object['lon'] = longitude
							result = osm_object['tags'].pop('addr:country', None)
							osm_element (osm_object, action="new")  # Create new addr node
							added += 1

						else:
							osm_object['lat'] = latitude
							osm_object['lon'] = longitude
							result = osm_object['tags'].pop('addr:country', None)
							osm_element (osm_object, action="modify")
							modified += 1

					for index in street_index.itervalues():
						if index['from'] > found_index:
							index['from'] -= 1
						if index['to'] >= found_index:
							index['to'] -= 1

					del osm_data['elements'][found_index]  # Remove match to speed up looping
					break

	message ('\rChecking addresses... %i\n' % (checked + 1))
	message ('  Addresses with street name:               %i\n' % validated)
	message ('  Addresses with full match:                %i\n' % matched)
	message ('  Addresses without full match:             %i\n' % (validated - matched))
	message ('  Addresses with corrected street names:    %i\n' % corrected)

	log (checked + 1, validated, matched, validated - matched, corrected)

	# 2nd pass:
	# Find all remaining "pure" address nodes at same location which will be updated with new address information
	# "Pure" address node are nodes which contain all of addr:street, addr:housenumber, addr:postcode, addr:city and no other tags
	# Remaining non-matched addresses are output as new address nodes

	message ("\nCompleting file %s...\n" % filename)

	checked2 = -1
	for row in addr_table2:
		checked2 += 1

		if row['adressenavn']:

			if not(found[checked2]):

				latitude = float(row['Nord'])
				longitude = float(row['Øst'])

				street = row['adressenavn'].decode('utf-8')
				housenumber = row['nummer'] + row['bokstav'].decode('utf-8')
				postcode = row['postnummer']
				city = row['poststed'].decode('utf-8').title().replace(" I "," i ")

				street, any_change = fix_street_name(street) 

				found_index = -1
				modify = False

				# Loop existing addr objects to find first close match with "pure" address node, to be modified
				# Consider the match close if distance is less than 1/1000 degrees

				for osm_object in osm_data['elements']:
					found_index += 1
					if osm_object['pure']:

						distance = math.sqrt((osm_object['lat'] - latitude) ** 2 + (osm_object['lon'] - longitude) ** 2)

						if distance < 0.0001:
							tag = osm_object['tags']
							if ('addr:housenumber' in tag) and ('addr:postcode' in tag) and ('addr:city' in tag):

								keep_object = osm_object.copy()
								del osm_data['elements'][found_index]
								modify = True
								break

				# Output new addr node to file if no match, or modified addr node if close location match
 
				if modify:
					modify_object = keep_object.copy()
					result = modify_object['tags'].pop('addr:country', None)
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

	# 3rd pass:
	# Output copy of remaining, non-matched addr objects to file (candidates for manual deletion of address tags and potentially also addr nodes)
	# Delete remaining "pure" addr nodes (they got no match)

	for osm_object in osm_data['elements']:

		# Delete "pure" address node
		if osm_object['pure']:
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
	message ('\nTime %i seconds (%i addresses per second)\n\n' % (time_spent, validated / time_spent))

	log (added, modified, deleted, len(osm_data['elements']) - deleted, int(time_spent), action="endline")


# Main program

if __name__ == '__main__':

	global debug

	total_start_time = time.time()
	message ("\n-- addr2osm v%s --\n" % version)

	if (len(sys.argv) == 2) and (len(sys.argv[1]) in [2,4]) and sys.argv[1].isdigit():
		entity = sys.argv[1]
		debug = False
	elif (len(sys.argv) == 3) and (len(sys.argv[1]) in [2,4]) and sys.argv[1].isdigit() and (sys.argv[2] == "-manual"):
		entity = sys.argv[1]
		debug = True
	else:
		sys.exit ('Usage: Please type "python addr2osm.py <nnnn>" with 4 digit municipality number or 2 digit county number\n'\
					+ '       Add "-manual" to get surplus address objects and DELETE tag\n')

	# Load municipality id's and names from Kartverket code list

	message ("Loading municipality and county codes from Kartverket\n")
	file = open_url("https://register.geonorge.no/api/sosi-kodelister/kommunenummer.json?")
	municipality_data = json.load(file)
	file.close()

	municipality = {}
	for mun in municipality_data['containeditems']:
		if (mun['status'] == "Gyldig") or (mun['codevalue'] == "2111"):  # Including Spitsbergen
			municipality[mun['codevalue']] = mun['label'].strip()

	# Load county id's and names from Kartverket code list

	file = open_url("https://register.geonorge.no/api/sosi-kodelister/fylkesnummer.json?")
	county_data = json.load(file)
	file.close()

	county = {}
	for coun in county_data['containeditems']:
		if coun['status'] == "Gyldig":
			county[coun['codevalue']] = coun['label'].strip()

	# Load corrections from Github, skip the first 47 sami corrections

	message ("Loading street name corrections from Github addr2osm/corrections.json\n")
	filename = "https://raw.githubusercontent.com/NKAmapper/addr2osm/master/corrections.json"
	file = open_url(filename)
	corrections = json.load(file)
	file.close()


	# Process either one municipality or all municipalities in one county

	if len(entity) == 4:

		if not(entity in municipality):
			sys.exit ('Municipality number %s not found' % entity)

		log (action="open")
		process_municipality (entity)
		log (action="close")

	else:

		if (entity != "99") and not(entity in county):
			sys.exit ('County number %s not found' % entity)

		if entity == "99":
			entity_name = "Norway (entire country)"
		else:
			entity_name = county[entity]

		message ("Generating addresses for %s..." % entity_name)
		log (action="open")
		municipality_count = 0

		for municipality_id in sorted(municipality.iterkeys()):

			if (entity == "99") or (municipality_id[0:2] == entity):
				process_municipality (municipality_id)
				municipality_count += 1

		message ("\nDone processing %i municipalities in %s\n" % (municipality_count, entity_name))
		time_spent = time.time() - total_start_time
		message ('\nTotal time %i:%02d minutes\n\n' % (time_spent / 60, time_spent % 60))
		log (action="close")
