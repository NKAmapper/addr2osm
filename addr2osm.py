#!/usr/bin/env python3
# -*- coding: utf8

# addr2osm.py
# Loads addresses from Kartverket and creates an osm file with updates, alternatively uploads to OSM.
# Usage: "python addr2osm.py <municipality id or county id> [-manual|-upload]".
# Optional "-upload" parameter will ask for username/password and upload to OSM,
# otherwise saves address changes to file with added DELETE tag + include surplus addr objects.


import json
import urllib.request, urllib.parse, urllib.error
import zipfile
from io import BytesIO, TextIOWrapper
import sys
import csv
import math
import time
import copy
import base64
from itertools import tee
from xml.etree import ElementTree as ET


version = "2.0.0"

debug = False

save_new_deleted = True  # Save new and deleted addresses to file (useful for discovering buildings and highways)

username = "addr2osm"

request_header = {"User-Agent": "addr2osm/" + version}

max_retries = 6

changeset_area = "county"  # Changeset partiion - "county" or "municipality". Note max 9900 changeset size.

first_municipality = ""  # Set to 4 digit municipality id to start iteration from a specfic municipality

osm_api = "https://api.openstreetmap.org/api/0.6/"  # Production database



# Compute approximation of distance between two coordinates, in meters.
# Works for short distances.
# Format: (lon, lat)

def compute_distance (p1, p2):

	lon1, lat1, lon2, lat2 = map(math.radians, [p1[0], p1[1], p2[0], p2[1]])
	x = (lon2 - lon1) * math.cos( 0.5*(lat2+lat1) )
	y = lat2 - lat1
	return 6371000 * math.sqrt( x*x + y*y )



# Open file/api, try up to 5 times, each time with double sleep time

def open_url (url):

	tries = 0
	while tries < max_retries:
		try:
			return urllib.request.urlopen(url)
		except urllib.error.HTTPError as e:
			if e.code in [429, 503, 504]:  # Too many requests, Service unavailable or Gateway timed out
				if tries  == 0:
					message ("\n") 
				message ("\rRetry %i... " % (tries + 1))
				time.sleep(5 * (2**tries))
				tries += 1
				error = e
			elif e.code in [401, 403]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Unauthorized or Blocked
				sys.exit()
			elif e.code in [400, 409, 412]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Bad request, Conflict or Failed precondition
				message ("%s\n" % str(e.read()))
				sys.exit()
			else:
				raise
	
	message ("\nHTTP error %i: %s\n" % (error.code, error.reason))
	sys.exit()



# Output message

def message (output_text):

	sys.stdout.write (output_text)
	sys.stdout.flush()



# Write to log file

def log (*args, **kwargs):

	global file_log

	if "action" in kwargs and kwargs['action'] == "open":
		filename = time.strftime("log_addr2osm_%d%b%Y_%H.%M.csv", time.localtime())
		file_log = open(filename, "w")
		output_text = "County;County name;Municipality;Municipality name;"\
						+ "OSM addresses;OSM parents;OSM children;Kartverket addresses;Kartverket street names;"\
						+ "Full match;Not full match;Corrected street names;New;Updated;Deleted;Remaining;Uploaded;Time\n"
		file_log.write (output_text)

	elif "action" in kwargs and kwargs['action'] == "close":
		file_log.close()

	else:
		for data in args:
			file_log.write(str(data))
			if not("action" in kwargs and kwargs['action'] == "endline"):
				file_log.write(";")
		if "action" in kwargs and kwargs['action'] == "endline":
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
		return "ÅÅÅ"  # Last in order



# Fix street name initials/dots and spacing. Return also True if anything changed.
# Examples:
#   Dr.Gregertsens vei -> Dr. Gregertsens vei
#   Arne M Holdens vei -> Arne M. Holdens vei
#   O G Hauges veg -> O.G. Hauges veg
#   C. A. Pihls gate -> C.A. Pihls gate

def fix_street_name (name):

	# First test exceptions from Github json file

	name = name.strip()

	if name in corrections:
		used_corrections.add(name)
		return corrections[ name ]

	# Loop characters in street name and make automatic corrections for dots and spacing

	new_name = ""
	length = len(name)

	i = 0
	word = 0  # Length of last word while looping street name

	while i < length - 3:  # Avoid last 3 characters to enable forward looking tests

		if name[i] == ".":
			if name[i + 1] == " " and name[i + 3] in [".", " "]:  # Example "C. A. Pihls gate"
				new_name = new_name + "." + name[i + 2]
				i += 2
				word = 1
			elif name[i + 1] != " " and name[i + 2] not in [".", " "]:  # Example "Dr.Gregertsens vei"
				new_name = new_name + ". "
				word = 0
			else:
				new_name = new_name + "."
				word = 0

		elif name[i] == " ":
			if word == 1 and name[i-1] not in ["-", "/", "Å"] and name[i+1] not in ["-", "/"]:  # Avoid "Rørsethornet P - plass", "Skjomenveien - Elvegård", "Å gate"
				if name[i + 2] in [" ", "."]:  # Example "O G Hauges veg"
					new_name = new_name + "."
				else:
					new_name = new_name + ". "  # Example "K Sundts vei"
			else:
				new_name = new_name + " "
			word = 0

		else:
			new_name = new_name + name[i]
			word += 1

		i += 1

	new_name = new_name + name[i:i + 3]

	if name != new_name:
		return new_name
	else:
		return name



# Generate OSM/XML for one OSM element, including for changeset
# Parameters:
# - element: Dict of OSM element in same format as returned by Overpass API
# - action:  Contains 'create', 'modify', 'delete' or 'output'

def generate_element (element, action):

	global osm_id    # Last OSM id generated (negative numbers)
	global uploaded  # Number of addresses to be uploaded

	if element is None:  # When recurse down more than one level
		return

	if element['type'] == "node":
		osm_element = ET.Element("node", lat=str(element['lat']), lon=str(element['lon']))

	elif element['type'] == "way":
		osm_element = ET.Element("way")
		if "nodes" in element:
			for node_ref in element['nodes']:
				osm_element.append(ET.Element("nd", ref=str(node_ref)))
				generate_element(find_element(node_ref), action="output")

	elif element['type'] == "relation":
		osm_element = ET.Element("relation")
		if "members" in element:
			for member in element['members']:
				osm_element.append(ET.Element("member", type=member['type'], ref=str(member['ref']), role=member['role']))
				generate_element(find_element(member['ref']), action="output")

	if "tags" in element:
		for key, value in iter(element['tags'].items()):
			osm_element.append(ET.Element("tag", k=key, v=value))

	if action == "create":
		osm_id -= 1	
		osm_element.set('id', str(osm_id))  # New id for new element
		osm_element.set('version', "1")
	else:
		osm_element.set('id', str(element['id']))
		osm_element.set('version', str(element['version']))
		osm_element.set('user', element['user'])
		osm_element.set('uid', str(element['uid']))
		osm_element.set('timestamp', element['timestamp'])
		osm_element.set('changeset', str(element['changeset']))

	if action == "delete":
		osm_element.append(ET.Element("tag", k="DELETE", v="yes"))  # Display in JOSM

	osm_root.append(osm_element)

	if action != "output":
		uploaded += 1
		osm_element.set('action', "modify")  # Override action for XML file
		if upload:
			action_element = ET.Element(action)
			action_element.append(osm_element)
			upload_root.append(action_element)
			if action in ["create", "delete"] and save_new_deleted:
				save_root.append(osm_element)



# Load OSM addresses for one municipality from Overpass

def load_osm_addresses (municipality_id):

	global osm_data			# Address elements downloaded from OSM, sorted by addr:street
	global osm_children		# Children elements downloaded from OSM
	global parents 			# Set of id for parents of osm_data
	global street_index 	# Dict with indexes into osm_data per street

	# Load Norwegian municipality name for given municipality number from parameter

	log (municipality_id[0:2], county[municipality_id[0:2]], municipality_id, municipality[ municipality_id ])

	# Load existing addr nodes in OSM for municipality

	message ("Loading existing addresses for %s from OSM Overpass... " % municipality[ municipality_id ])

	query = (	'[out:json][timeout:90];'
				'(area[ref=%s][admin_level=7][place=municipality];)->.a;'
				'(nwr[~"addr:"~".*"](area.a););'
				'out center meta;' ) % (municipality_id)

	if municipality_id == "2100":
		query = query.replace("[ref=2100][admin_level=7][place=municipality]", "[name=Svalbard][admin_level=4]")

	count = 0
	osm_data = { 'elements': [] }
	while not osm_data['elements'] and count < 5:  # Load could be empty from Overpass
		request = urllib.request.Request("https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query), headers=request_header)
		file = open_url(request)
		osm_data = json.load(file)
		file.close()
		count += 1

	street_index = dict()

	if osm_data['elements']:

		# Sort list and make index to speed up matching

		osm_data['elements'].sort(key=addr_sort)
		if "addr:street" in osm_data['elements'][0]['tags']:
			last_street = osm_data['elements'][0]['tags']['addr:street']
			street_index[last_street] = {'from': 0, 'to': 0}
		else:
			last_street = None

		i = -1
		for element in osm_data['elements']:
			i += 1

			if "addr:street" in element['tags']:
				this_street = element['tags']['addr:street']
				if this_street != last_street:
					street_index[last_street]['to'] = i - 1
					street_index[this_street] = {'from': i, 'to': 0}
					last_street = this_street

		if last_street:
			street_index[last_street]['to'] = i

		# Set "clean" flag if only "addr:" tags, and no other tags
		# Set "pure" flag if all of addr:street, addr:housenumber, addr:postcode, addr:city + optionaly addr:country are present, and no other tags

		for element in osm_data['elements']:

			if element['type'] == "node":
				addr_count = 0
				clean = True
				pure = True

				for tag in element['tags']:
					if tag in ["addr:street", "addr:housenumber", "addr:postcode", "addr:city"]:
						addr_count += 1
					elif tag != "addr:country":
						pure = False
						if tag[0:5] != "addr:":
							clean = False

				element['clean'] = clean
				element['pure'] = (clean and pure and (addr_count == 4))

			else:
				element['clean'] = False
				element['pure'] = False


	message ("%i" % (len(osm_data['elements'])))
	log (len(osm_data['elements']))

	# Recurse up to get any parents

	query = query.replace("out center meta", "<;out meta")
	request = urllib.request.Request("https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query), headers=request_header)
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

	# Recurse down to get any childen

	if not upload or debug:
		query = query.replace("<;out meta", ">;out meta")
		request = urllib.request.Request("https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query), headers=request_header)
		file = open_url(request)
		osm_children = json.load(file)
		file.close()
		message (" +%i child objects" % (len(osm_children['elements'])))
	else:
		osm_children = { 'elements': [] }

	log (len(osm_children['elements']))



# Process one municipality

def process_municipality (municipality_id):

	global osm_id 		# Last OSM id generated (negative numbers)
	global uploaded 	# Number of elements to be uploaded

	# Load addresses from OSM

	start_time = time.time()
	message ("\n\n%s %s\n" % (municipality_id, municipality[ municipality_id ]))
	load_osm_addresses(municipality_id)

	# Load latest address file for municipality from Kartverket

	filename = "Basisdata_%s_%s_4258_MatrikkelenVegadresse_CSV" % (municipality_id, municipality[ municipality_id ])
	filename = filename.replace("Æ","E").replace("Ø","O").replace("Å","A").replace("æ","e").replace("ø","o").replace("å","a")
	filename = filename.replace(" ", "_")

	message ("\nLoading address file '%s' from Kartverket\n" % filename)

	file_in = open_url("https://nedlasting.geonorge.no/geonorge/Basisdata/MatrikkelenVegadresse/CSV/" + filename + ".zip")
	zip_file = zipfile.ZipFile(BytesIO(file_in.read()))
	csv_file = zip_file.open(filename + "/matrikkelenVegadresse.csv")
	addr_table1, addr_table2 = tee(csv.DictReader(TextIOWrapper(csv_file, "utf-8"), delimiter=";"), 2)

	# Initiate loop

	matched = 0
	added = 0
	modified = 0
	deleted = 0
	validated = 0
	corrected = 0

	found = []  # Index list which Will contain True for matched adresses from Kartverket 

	message ("\nChecking addresses...")

	# 1st pass:
	# Find all 100% matches betweem Kartverket and OSM

	checked = -1

	for row in addr_table1:

		checked += 1
		found.append(False)

		if (checked + 1) % 1000 == 0:
				message ("\rChecking addresses... %i" % (checked + 1))

		if row['adressenavn']:

			validated += 1

			latitude = float(row['Nord'])
			longitude = float(row['Øst'])

			street = row['adressenavn']
			housenumber = row['nummer'] + row['bokstav']
			postcode = row['postnummer']
			city = row['poststed'].title().replace(" I "," i ")

			new_street = fix_street_name(street)
			if new_street != street:
				street = new_street
				corrected += 1

			if street not in street_index:
				continue

			found_index = street_index[street]['from'] - 1

			# Loop existing addr objects from OSM to find first exact match of "pure" address node

			for osm_object in osm_data['elements'][ street_index[street]['from'] : street_index[street]['to'] + 1 ]:
				found_index += 1
				tags = osm_object['tags']

				if (osm_object['pure']
						and housenumber == tags['addr:housenumber']
						and street == tags['addr:street']
						and postcode == tags['addr:postcode']
						and city == tags['addr:city']):

					found[ checked ] = True
					matched += 1

					distance = compute_distance((longitude, latitude), (osm_object['lon'], osm_object['lat']))

					# Modify object coordinates if it has been relocated more than 1 meter.
					# Keep the existing node if it has parents.

					if distance > 1.0 or 'addr:country' in tags:

						if osm_object['id'] in parents:
							modify_object = copy.deepcopy(osm_object)
							modify_object['tags'] = {}
							generate_element (modify_object, action="modify")  # Keep empty node if parents
							modified += 1

							osm_object['lat'] = latitude
							osm_object['lon'] = longitude
							osm_object['tags'].pop('addr:country', None)
							generate_element (osm_object, action="create")  # Create new addr node
							added += 1

						else:
							osm_object['lat'] = latitude
							osm_object['lon'] = longitude
							osm_object['tags'].pop('addr:country', None)
							generate_element (osm_object, action="modify")
							modified += 1

					for index in iter(street_index.values()):
						if index['from'] > found_index:
							index['from'] -= 1
						if index['to'] >= found_index:
							index['to'] -= 1

					del osm_data['elements'][ found_index ]  # Remove match to speed up looping later
					break

	# Report

	message ("\rChecking addresses... %i\n" % (checked + 1))
	message ("\tAddresses in cadastral source:            %i\n" % validated)
	if debug:
		message ("\tAddresses with match:                     %i\n" % matched)
		message ("\tAddresses without match:                  %i\n" % (validated - matched))
		message ("\tAddresses with corrected street names:    %i\n\n" % corrected)

	log (checked + 1, validated, matched, validated - matched, corrected)

	# 2nd pass:
	# Find all remaining "pure" address nodes at same location which will be updated with new address information
	# "Pure" address node are nodes which contain all of addr:street, addr:housenumber, addr:postcode, addr:city and no other tags
	# Remaining non-matched addresses are output as new address nodes

#	message ("\nCompleting update ... ")

	checked2 = -1
	for row in addr_table2:
		checked2 += 1

		if row['adressenavn']:

			if not found[ checked2 ]:

				latitude = float(row['Nord'])
				longitude = float(row['Øst'])

				street = row['adressenavn']
				housenumber = row['nummer'] + row['bokstav']
				postcode = row['postnummer']
				city = row['poststed'].title().replace(" I "," i ")

				street = fix_street_name(street) 

				found_index = -1
				modify = False

				# Loop existing addr objects to find first close match with "pure" address node, to be modified
				# Consider the match close if distance is less than 10 meters

				for osm_object in osm_data['elements']:
					found_index += 1
					if osm_object['clean']:

						distance = compute_distance((longitude, latitude), (osm_object['lon'], osm_object['lat']))

						if distance < 10.0:  # meters
							keep_object = copy.deepcopy(osm_object)
							del osm_data['elements'][ found_index ]
							modify = True
							break

				# Output new addr node to file if no match, or modified addr node if close location match
 
				if modify:
					modify_object = copy.deepcopy(keep_object)
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
						generate_element (keep_object, action="modify")  # Keeo empty node if parents
						modified += 1

						generate_element (modify_object, action="create")  # Create new addr node
						added += 1

					else:
						generate_element (modify_object, action="modify")
						modified += 1

				else:
					generate_element (modify_object, action="create")
					added += 1

	# 3rd pass:
	# Output copy of remaining, non-matched addr objects to file (candidates for manual deletion of address tags and potentially also addr nodes)
	# Delete remaining "clean" addr nodes (they got no match).
	# Remove addr tags from ways and relations (addr tags will be on separate addr nodes)

	for osm_object in osm_data['elements']:

		if osm_object['clean']:
			# Delete "pure" address node

			if osm_object['id'] in parents:
				keep_object = copy.deepcopy(osm_object)
				keep_object['tags'] = {}
				generate_element (keep_object, action="modify")  # Keep empty node if parents
				modified += 1
			else:
				deleted += 1
				generate_element (osm_object, action="delete")

		else:
			# Delete "addr:" tags, except if "addr" is included in note=*
			# Add any handling of buildings or features (amenity etc) in this section, if desired.

			modify_object = copy.deepcopy(osm_object)
			found_addr_tag = False
			found_other_tag = False
			found_note = False

			for tag in osm_object['tags']:
				if tag[0:5] == "addr:":
					modify_object['tags'].pop(tag)
					found_addr_tag = True
#				elif (tag in ["amenity", "leisure", "tourism", "shop", "office", "craft", "club"]):  # (earlier strategy, replaced by note)
				elif tag == "note" and "addr" in osm_object['tags'][tag]:  # Opt-out note found
					found_note = True
				elif "image" not in tag and "note" not in tag and "mapillary" not in tag:
					found_other_tag = True

			if found_addr_tag and not found_note:
				if found_other_tag or osm_object['id'] in parents:
#					modify_object['lat'] += 0.00005  # Offset approx 5 meters from addr node
					generate_element (modify_object, action="modify")
					modified += 1
				else:
					generate_element (osm_object, action="delete")
					deleted += 1
			else:
				generate_element (osm_object, action="output")  # No proper addr tag or opt-out note found

	file_in.close()

	# Report

	message ("\tNew addresses:                            %i\n" % added)
	message ("\tUpdated existing address nodes:           %i\n" % modified)
	message ("\tDeleted existing address nodes:           %i\n" % deleted)
	message ("\tTotal changeset elements:                 %i\n" % uploaded)
	message ("\tRemaining addresses in OSM without match: %i\n" % (len(osm_data['elements']) - deleted))

	# Report time used

	time_spent = time.time() - start_time
	message ("\nTime %i seconds (%i addresses per second)\n" % (time_spent, validated / time_spent))

	log (added, modified, deleted, len(osm_data['elements']) - deleted, uploaded)
	log (int(time_spent), action="endline")



# Create XML roots, to be output later

def init_root():

	global osm_root		# XML of all addresses in municipality
	global upload_root	# XML to be uploaded to OSM
	global save_root 	# XML of all deleted addresses during run
	global uploaded 	# Number of elements to be uploaded

	uploaded = 0
	osm_root = ET.Element("osm", version="0.6", generator="addr2osm v%s" % version, upload="false")
	upload_root = ET.Element("osmChange", version="0.6", generator="nsr2osm")
	if "save_root" not in globals():
		save_root = ET.Element("osm", version="0.6", generator="addr2osm v%s" % version, upload="false")



# Upload changeset to OSM

def upload_changeset(entity_id, entity_name, changeset_count):

	if upload and changeset_count > 0:

		if changeset_count < 9900:  # Maximum upload is 10.000 elements
			
			today_date = time.strftime("%Y-%m-%d", time.localtime())

			changeset_root = ET.Element("osm")
			changeset_element = ET.Element("changeset")
			changeset_element.append(ET.Element("tag", k="comment", v="Address import update for %s" % entity_name))
			changeset_element.append(ET.Element("tag", k="source", v="Kartverket: Matrikkelen Vegadresse"))
			changeset_element.append(ET.Element("tag", k="source:date", v=today_date))
			changeset_root.append(changeset_element)
			changeset_xml = ET.tostring(changeset_root, encoding='utf-8', method='xml')

			request = urllib.request.Request(osm_api + "changeset/create", data=changeset_xml, headers=osm_request_header, method="PUT")
			file = open_url(request)  # Create changeset
			changeset_id = file.read().decode()
			file.close()	

			message ("Uploading %i elements for %s to OSM in changeset #%s... " % (changeset_count, entity_name, changeset_id))

			for element in upload_root:
				element[0].set("changeset", changeset_id)  # Update changeset for element

			indent_tree(upload_root)
			changeset_xml = ET.tostring(upload_root, encoding='utf-8', method='xml')

			request = urllib.request.Request(osm_api + "changeset/%s/upload" % changeset_id, data=changeset_xml, headers=osm_request_header)
			file = open_url(request)  # Post changeset in one go
			file.close()

			request = urllib.request.Request(osm_api + "changeset/%s/close" % changeset_id, headers=osm_request_header, method="PUT")
			file = open_url(request)  # Close changeset
			file.close()

			if debug:
				file_out = open("addr_changeset.xml", "w")
				file_out.write(changeset_xml.decode())
				file_out.close()

			message ("Done\n")
			return True

		else:
			message ("\n\nCHANGESET TOO LARGE (%i) - UPLOAD MANUALLY WITH JOSM\n\n" % uploaded)
			not_uploaded.append("%s %s" % (entity_id, entity_name))

	if not upload and changeset_count > 0 or upload and changeset_count >= 9900 or debug:
		osm_tree = ET.ElementTree(osm_root)
		indent_tree(osm_root)
		out_filename = "address_import_%s_%s.osm" % (entity_id, entity_name)
		out_filename = out_filename.replace(" ", "_")
		osm_tree.write(out_filename, encoding="utf-8", method="xml", xml_declaration=True)
		message ("Saved to file '%s'\n" % out_filename)

	return False



# Insert line feeds into XLM file.

def indent_tree(elem, level=0):

	i = "\n" + level*"  "
	if len(elem):
		if not elem.text or not elem.text.strip():
			elem.text = i + "  "
		if not elem.tail or not elem.tail.strip():
			elem.tail = i
		for elem in elem:
			indent_tree(elem, level+1)
		if not elem.tail or not elem.tail.strip():
			elem.tail = i
	else:
		if level and (not elem.tail or not elem.tail.strip()):
			elem.tail = i



# Get authorization for later uploading to OSM.
# Returns request header for uploading.

def get_password():

	message ("This program will automatically upload bus stop changes to OSM\n")
	password = input ("Please enter OSM password for '%s' user: " % username)

	authorization = username.strip() + ":" + password.strip()
	authorization = "Basic " + base64.b64encode(authorization.encode()).decode()
	osm_request_header = request_header
	osm_request_header.update({'Authorization': authorization})

	request = urllib.request.Request(osm_api + "permissions", headers=osm_request_header)
	file = open_url(request)
	permissions = file.read().decode()
	file.close()

	if "allow_write_api" not in permissions:  # Authorized to modify the map
		sys.exit ("Wrong username/password or not authorized\n")

	return osm_request_header



# Main program

if __name__ == '__main__':

	total_start_time = time.time()
	message ("\n-- addr2osm v%s --\n" % version)

	if (len(sys.argv) in [2,3] and len(sys.argv[1]) in [2,4] and sys.argv[1].isdigit()
			and (len(sys.argv) == 2 or sys.argv[2] == "-upload")):
		entity = sys.argv[1]
		upload = ("-upload" in sys.argv)
	else:
		sys.exit (('Usage: Please type "python addr2osm.py <nnnn>" with 4 digit municipality number or 2 digit county number\n'
					'       Add "-upload" to automatically upload changes to OSM\n'))

	# Check OSM username/password

	if upload:
		osm_request_header = get_password()

	# Load municipality id's and names from Kartverket api

	message ("Loading municipality and county codes from Kartverket\n")
	file = open_url("https://ws.geonorge.no/kommuneinfo/v1/kommuner")
	municipality_data = json.load(file)
	file.close()

	municipality = {}
	for mun in municipality_data:
		municipality[ mun['kommunenummer'] ] = mun['kommunenavnNorsk'].strip()
	municipality['2100'] = "Svalbard"

	# Load county id's and names from Kartverket api

	file = open_url("https://ws.geonorge.no/kommuneinfo/v1/fylker")
	county_data = json.load(file)
	file.close()

	county = {}
	for coun in county_data:
		county[ coun['fylkesnummer'] ] = coun['fylkesnavn'].strip()
	county['21'] = "Svalbard"

	# Load corrections from Github

	message ("Loading street name corrections from Github 'addr2osm/corrections.json'\n")
	filename = "https://raw.githubusercontent.com/NKAmapper/addr2osm/master/corrections.json"
	file = open_url(filename)
	corrections = json.load(file)
	file.close()
	used_corrections = set()  # Will contain corrections used

	# Process either one municipality or all municipalities in one county.
	# Uploading to OSM either per municipality or per county.

	osm_id = -1000
	not_uploaded = []  # Will contain counties/municipalities not uploaded due to changeset size

	if len(entity) == 4:
		if entity not in municipality:
			sys.exit ("Municipality number %s not found" % entity)

		entity_name = municipality[ entity ]
		log (action="open")
		init_root()
		process_municipality (entity)
		upload_changeset(entity, entity_name, uploaded)
		log (action="close")
		message ("\n")

	else:
		if entity != "00" and entity not in county:
			sys.exit ("County number %s not found" % entity)

		if entity == "00":
			entity_name = "Norway (entire country)"
		else:
			entity_name = county[entity]

		message ("Generating addresses for %s...\n" % entity_name)
		log (action="open")
		municipality_count = 0
		total_uploaded = 0

		for county_id in sorted(county.keys()):
			if entity == "00" or county_id == entity:
				init_root()
				county_uploaded = 0

				for municipality_id in sorted(municipality.keys()):
					if municipality_id[0:2] == county_id and municipality_id >= first_municipality:
						process_municipality (municipality_id)
						total_uploaded += uploaded
						county_uploaded += uploaded
						municipality_count += 1

						if changeset_area == "municipality":
							upload_changeset(municipality_id, municipality[ municipality_id ], uploaded)
							init_root()

				if changeset_area == "county" and county_uploaded > 0:
					message ("\n\n")
					upload_changeset(county_id, county[ county_id ], county_uploaded)

		message ("\nDone processing %i municipalities in %s, %i changes\n" % (municipality_count, entity_name, total_uploaded))
		time_spent = time.time() - total_start_time
		message ("Total time %i:%02d minutes\n\n" % (time_spent / 60, time_spent % 60))
		log (action="close")

		if not_uploaded:
			message ("Upload these counties/municipalities manually (files have been generated):\n")
			for line in not_uploaded:
				message ("\t%s\n" % line)
			message ("\n")

	# Save file with new and deleted addresses (indication of buildings to be modified)

	if upload and save_new_deleted:
		save_tree = ET.ElementTree(save_root)
		indent_tree(save_root)
		out_filename = "new_deleted_addresses.osm"
		save_tree.write(out_filename, encoding="utf-8", method="xml", xml_declaration=True)

	# Report corrections used

	if used_corrections and entity == "00":
		filename = "addr_corrections.json"
		file = open(filename, "w")
		file.write("{\n")
		for street in sorted(used_corrections):
			file.write('  "%-30s "%s",\n' % (street + '":', corrections[ street ]))  # Format in two colums
		file.write("}\n")
		file.close()
		message ("\n\n")
