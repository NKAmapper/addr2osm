#!/usr/bin/env python3
# -*- coding: utf8

# addr2osm.py Sverige
# Loads addresses from Lantmäteriet and creates an osm file with updates, alternatively uploads to OSM.
# Usage: "python addr2osm.py <municipality id or county id> [-manual|-upload]".
# Optional "-upload" parameter will ask for username/password and upload to OSM,
# otherwise saves address changes to file with added DELETE tag + include surplus addr objects.
# Optional "-source" paramter will just save Lantmäteriet addresses to file without uplaod.


import json
import urllib.request, urllib.parse, urllib.error
import zipfile
import io
import os.path
import sys
import math
import time
from xml.etree import ElementTree as ET
from geopandas import gpd
import warnings

warnings.filterwarnings(
    action="ignore",
    message=".*has GPKG application_id, but non conformant file extension.*"
)


version = "0.2.0"

debug = False

save_new_deleted = False 		# Save new and deleted addresses to file (useful for discovering buildings and highways)

username = "addr2osm"			# Upload to OSM with this account

max_retries = 6 				# Max number of retries for Overpass API

changeset_area = "municipality"	# Changeset partiion - "county" or "municipality". Note max 9900 changeset size.

max_relocation = 25  			# Maximum relocation for an addr node (meters)
min_relocation = 1 				# Minimum relocation

include_housename = False 		# Include "popular name" as addr:housename

first_municipality = ""			# Set to 4 digit municipality id to start iteration from a specfic municipality

request_header = {"User-Agent": "addr2osm/" + version}

osm_api = "https://api.openstreetmap.org/api/0.6/"  # Production database
overpass_api = "https://overpass-api.de/api/interpreter"

osm_token_filename = "~/Google Drive/Min disk/diverse/Adresser/addr2osm_token.txt"  # OAuth2 access token for OSM
lm_token_filename = "~/downloads/geotorget_token.txt"	# Stored Geotorget credentials



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



# Load municipality/county id's and names from GitHub

def load_municipalities ():

	message ("Loading municipality and county codes\n")

	# Load municipalities

	url = "https://gist.githubusercontent.com/vincentorback/90c31b4231449a5d159ba29d3cafa441/raw/f3de36d70e75f1c67769c9c9abbaadee8bba3e23/municipalities.json"
	try:
		file = urllib.request.urlopen(url)
	except urllib.error.HTTPError as e:
		sys.exit("\t*** Failed to load municiaplity names from GitHub, HTTP error %i: %s\n\n" % (e.code, e.reason))
	municipality_data = json.load(file)
	file.close()

	municipalities['00'] = "Sverige"
	for municipality in municipality_data:
		municipalities[ municipality['id'] ] = municipality['name'].strip()

	# Load counties

	url = "https://gist.githubusercontent.com/vincentorback/90c31b4231449a5d159ba29d3cafa441/raw/f3de36d70e75f1c67769c9c9abbaadee8bba3e23/counties.json"
	try:
		file = urllib.request.urlopen(url)
	except urllib.error.HTTPError as e:
		sys.exit("\t*** Failed to load county names from GitHub, HTTP error %i: %s\n\n" % (e.code, e.reason))
	county_data = json.load(file)
	file.close()

	for county in county_data:
		counties[ county['id'] ] = county['name'].strip()
		municipalities[ county['id'] ] = county['name'].strip()  # Add to enable county selection in get_municipality()



# Identify municipality or county name, unless more than one hit.
# Returns municipality or county number, or 00 for Sweden.

def get_municipality (parameter):

	# Identify chosen municipality

	if parameter.isdigit() and parameter in municipalities:
		return parameter
	else:
		found_ids = []
		for mun_id, mun_name in iter(municipalities.items()):
			if parameter.lower() == mun_name.lower():
				return mun_id
			elif parameter.lower() in mun_name.lower():
				found_ids.append(mun_id)

		if len(found_ids) == 1:
			return found_ids[0]
		elif not found_ids:
			sys.exit("*** Municipality '%s' not found\n\n" % parameter)
		else:
			mun_list = [ "%s %s" % (mun_id, municipalities[ mun_id ]) for mun_id in found_ids ]
			sys.exit("*** Multiple municipalities found for '%s' - please use full name:\n%s\n\n" % (parameter, ", ".join(mun_list)))



# Get authorization for later uploading to OSM.
# Returns request header for uploading.

def get_osm_token():

	message ("Loading OSM credentials from file '%s'\n" % osm_token_filename)

	full_filename = os.path.expanduser(osm_token_filename)
	if os.path.isfile(full_filename):
		file = open(full_filename)
		token = file.read()
		file.close()
	else:
		sys.exit("Please store OAuth2 token in '%s' file\n" % osm_token_filename)

	osm_request_header = request_header.copy()
	osm_request_header.update({'Authorization': 'Bearer ' + token})

	request = urllib.request.Request(osm_api + "permissions", headers=osm_request_header)
	file = open_url(request)
	permissions = file.read().decode()
	file.close()

	if "allow_write_api" not in permissions:  # Authorized to modify the map
		sys.exit ("Wrong OAuth2 token or missing OSM authorization\n")

	confirm = input ("Please confirm automatic upload of address changes to OSM (Y/N): ")
	if confirm.lower() != "y":
		sys.exit("Not confirmed\n")

	return osm_request_header



# Get stored Geotorget token or ask for credentials

def get_lm_token():

	filename = lm_token_filename.split("/")[-1]

	if not os.path.isfile(filename):
		test_filename = os.path.expanduser(lm_token_filename)
		if os.path.isfile(test_filename):
			filename = test_filename

	if os.path.isfile(filename):		
		message ("Loading Geotorget credentials from file '%s'\n\n" % filename)
		file = open(filename)
		token = file.read()
		file.close()
	else:
		message ("Please provide Geotorget login (you need approval for 'Belägenhetsadress Nedladdning, vektor') ...\n")
		username = input("\tUser name: ")
		password = input("\tPassword:  ")
		token = username + ":" + password
		token = base64.b64encode(token.encode()).decode()
		file = open(filename, "w")
		file.write(token)
		file.close()
		message ("\tStoring credentials in file '%s'\n\n" % filename)

	return token



# Load addresses from Lantmäteriet

def load_lm_addresses (municipality_id):

	global lm_addresses  # Will contain all addresses

	# Load from Geotorget

	message ("Loading %s from Lantmäteriet ... " % municipality_id)

	header = { 'Authorization': 'Basic ' +  lm_token }
	url = "https://dl1.lantmateriet.se/adress/belagenhetsadresser/belagenhetsadresser_kn%s.zip" % municipality_id
	filename = "belagenhetsadresser_kn%s.gpkg" % municipality_id
	request = urllib.request.Request(url, headers = header)

	try:
		file_in = urllib.request.urlopen(request)
	except urllib.error.HTTPError as e:
		message ("\t*** HTTP error %i: %s\n" % (e.code, e.reason))
		if e.code == 401:  # Unauthorized
			message ("\t*** Wrong username (email) or password, or you need approval for 'Belägenhetsadress Nedladdning, vektor' at Geotorget\n\n")
			os.remove(lm_token_filename)
			sys.exit()
		elif e.code == 403:  # Blocked
			sys.exit()
		else:
			return

	zip_file = zipfile.ZipFile(io.BytesIO(file_in.read()))
	file = zip_file.open(filename)

	gdf = gpd.read_file(file, layer="belagenhetsadress")

	file.close()
	zip_file.close()
	file_in.close()

	gdf = gdf.to_crs("EPSG:4326")  # Transform projection from EPSG:3006
	gdf['versiongiltigfran'] = gdf['versiongiltigfran'].dt.strftime("%Y-%m-%d")  # Fix type

	# Load and tag addresses

	lm_addresses = []

	for feature in gdf.iterfeatures(na="drop", drop_id=True):
		properties = feature['properties']
		point = feature['geometry']['coordinates']
		tags = {}

		# Skip incomplete data
		if "postort" not in properties or properties['postnummer'] == 0 or properties['statusforbelagenhetsadress'] != "Gällande":
			continue

		street = ""
		if properties['adressplatstyp'] in ["Gatuadressplats", "Metertalsadressplats"]:
			street = properties['adressomrade_faststalltnamn'].strip()
			tags['addr:street'] = street
		elif properties['adressplatstyp'] == "Byadressplats":
			street = properties['adressomrade_faststalltnamn'].strip()
			tags['addr:place'] = street
		elif properties['adressplatstyp'] == "Gårdsadressplats":
			street = properties['adressomrade_faststalltnamn'].strip()
			if "gardsadressomrade_faststalltnamn" in properties and properties['gardsadressomrade_faststalltnamn']:
				street += " " + properties['gardsadressomrade_faststalltnamn'].strip()
			tags['addr:place'] = street

		number = ""
		if ("adressplatsnummer" in properties and properties['adressplatsnummer']
				or properties['avvikerfranstandarden'] and properties['avvikandeadressplatsbeteckning']):

			if properties['avvikerfranstandarden']:
				number = properties['avvikandeadressplatsbeteckning'].strip()
			else:
				number = properties['adressplatsnummer'].strip()

			if "bokstavstillagg" in properties and properties['bokstavstillagg']:
				number += properties['bokstavstillagg']
			if "lagestillagg" in properties and properties['lagestillagg']:
				number += " " + properties['lagestillagg'].strip()
				if "lagestillaggsnummer" in properties:
					number += str(properties['lagestillaggsnummer'])

			tags['addr:housenumber'] = number			

		tags['addr:district'] = properties['kommundel_faststalltnamn'].strip()
		tags['addr:postcode'] = str(properties['postnummer'])
		tags['addr:city'] = properties['postort'].strip()

		if include_housename and "popularnamn" in properties and properties['popularnamn'].strip():
			tags['addr:housename'] = properties['popularnamn'].strip()

		# Create index key for direct matching with OSM later
		index = (street, number, tags['addr:postcode'], tags['addr:city'])   # Add later: "addr:district" 

		address = {
			'type': properties['adressplatstyp'],
			'tags': tags,
			'point': (round(point[0], 6), round(point[1], 6)),
			'index': index
		}
		lm_addresses.append(address)

	message ("%i\n" % len(lm_addresses))



# Load OSM addresses for one municipality from Overpass

def load_osm_addresses (municipality_id):

	global osm_data				# Address elements downloaded from OSM, sorted by addr:street
	global osm_children			# Children elements downloaded from OSM
	global parents 				# Set of id for parents of osm_data
	global osm_addr_index 		# Dict with indexes into osm_data
	global osm_children_index	# Dict with indexes into osm_children

	# Load existing addr nodes in OSM for municipality

	message ("Loading existing addresses for %s from OSM Overpass... " % municipalities[ municipality_id ])

	query = (	'[out:json][timeout:120];'
				'(area["ref:scb"=%s][admin_level=7];)->.a;'
				'(nwr[~"addr:"~".*"](area.a););'
				'out center meta;' ) % municipality_id

	count = 0
	osm_data = { 'elements': [] }
	while not osm_data['elements'] and count < 5:  # Load could be empty from Overpass
		request = urllib.request.Request(overpass_api + "?data=" + urllib.parse.quote(query), headers=request_header)
		file = open_url(request)
		osm_data = json.load(file)
		file.close()
		count += 1

	# Create index to speed up matching later

	osm_addr_index = dict()
	osm_addr_ids = set()

	for element in osm_data['elements']:
		tags = element['tags']
		osm_addr_ids.add(element['id'])
		index = [None, None, None, None]

		if "addr:street" in tags:
			index[0] = tags['addr:street']
		elif "addr:place" in tags:
			index[0] = tags['addr:place']

		if "addr:housenumber" in tags:
			index[1] = tags['addr:housenumber'].upper()

		if "addr:postcode" in tags:
			index[2] = tags['addr:postcode'].replace(" ", "")

		# Add addr:district later

		if "addr:city" in tags:
			index[3] = tags['addr:city']

		if index != [None, None, None, None]:
			index = tuple(index)
			osm_addr_index[ index ] = element

	# Set "clean" flag if only relevant "addr:" tags, and no other tags

	for element in osm_data['elements']:
		if element['type'] == "node":
			addr_count = 0
			clean = True

			for tag in element['tags']:
				if tag in ["addr:street", "addr:place", "addr:housenumber", "addr:district", "addr:postcode", "addr:city"]:
					addr_count += 1
				elif tag[0:5] != "addr:" and "fixme" not in tag.lower() and "source" not in tag and tag != "created_by":
					clean = False

			if clean and addr_count > 0:
				element['clean'] = True

	message ("%i" % (len(osm_data['elements'])))

	# Recurse up to get any parents

	query = query.replace("out center meta", "<;out meta")
	request = urllib.request.Request(overpass_api + "?data=" + urllib.parse.quote(query), headers=request_header)
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

	# Recurse down to get any childen

	if not upload or debug:
		query = query.replace("<;out meta", ">;out meta")
		request = urllib.request.Request(overpass_api + "?data=" + urllib.parse.quote(query), headers=request_header)
		file = open_url(request)
		osm_children = json.load(file)
		file.close()
		message (" +%i child objects" % (len(osm_children['elements'])))

		# Generate index to children for faster access

		osm_children_index = dict()
		for element in osm_children['elements']:
			if element['id'] not in osm_addr_ids:
				osm_children_index[ element['id'] ] = element

	else:
		osm_children = { 'elements': [] }
		osm_children_index = dict()

	message ("\n")



# Return osm child/member object in "recurse down" list from Overpass

def child_element (id_no):

	if id_no in osm_children_index:
		return osm_children_index[ id_no ]
	else:
		return None



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
				generate_element(child_element(node_ref), action="output")

	elif element['type'] == "relation":
		osm_element = ET.Element("relation")
		if "members" in element:
			for member in element['members']:
				osm_element.append(ET.Element("member", type=member['type'], ref=str(member['ref']), role=member['role']))
				generate_element(child_element(member['ref']), action="output")

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



# Update OSM addresses with Lantmäteriet for one municipality

def merge_addresses (municipality_id):

	global osm_id 		# Last OSM id generated (negative numbers)
	global uploaded 	# Number of elements to be uploaded

	validated = 0
	matched = 0
	added = 0
	modified = 0
	deleted = 0
	removed = 0
	uploaded = 0
	remaining = 0


	# 1st pass:

	# Update all clean direct matches betweem Lantmäteriet and OSM

	for lm_addr in lm_addresses:

		validated += 1

		if lm_addr['index'] not in osm_addr_index:  # No direct mnatch
			continue

		osm_object = osm_addr_index[ lm_addr['index'] ]

		if "clean" in osm_object:
			distance = compute_distance(lm_addr['point'], (osm_object['lon'], osm_object['lat']))

			if distance < 200:  # Avoid large gaps, even for direct hits

				# Modify object coordinates if it has been relocated more than 1 meter.

				if distance > min_relocation:
					new_object = {
						'type': 'node',
						'lat': lm_addr['point'][1],
						'lon': lm_addr['point'][0],
						'tags': lm_addr['tags']
					}

					# Keep the existing node if it has a parent and create a new address node.

					if osm_object['id'] in parents:
						osm_object['tags'] = {}
						generate_element (osm_object, action="modify")  # Keep empty node if parents
						modified += 1

						generate_element (new_object, action="create")  # Create new addr node
						added += 1

					else:
						osm_object['tags'] = lm_addr['tags']
						osm_object['lat'] = lm_addr['point'][1]
						osm_object['lon'] = lm_addr['point'][0]
						generate_element (osm_object, action="modify")
						modified += 1

				else:
					if osm_object['tags'] != lm_addr['tags']:  # Ensure correct tagging
						osm_object['tags'] = lm_addr['tags']
						generate_element (osm_object, action="modify")
						modified += 1
					else: 
						generate_element (osm_object, action="output")

				# Mark match as found and for no further action

				osm_object['found'] = True
				lm_addr['found'] = True
				matched += 1


	# 2nd pass:

	# Find all remaining "clean" address nodes around the same location. Will be updated with new address information.
	# "Clean" address node are nodes which contain all of addr:street/addr:place, addr:housenumber, addr:postcode, addr:city and no other tags.
	# Remaining non-matched Lantmäteriet addresses are output as new address nodes.

	# Create shorter list of OSM matching candidates to speed up iterations

	osm_addr_elements = []
	for osm_object in osm_data['elements']:
		if "clean" in osm_object and "found" not in osm_object:
			osm_addr_elements.append(osm_object)

	# Loop remaining Lantmäteriet addresses

	count = validated - matched
	for lm_addr in lm_addresses:

		if "found" in lm_addr:
			continue

		count -= 1
		if count % 1000 == 0:
			message ("\r%i " % count)

		# Loop existing OSM addr objects to find best close match with "pure" address node, to be modified.
		# House number is required to match, to avoid strange node history.

		best_distance = max_relocation  # Minimum meters distance
		found = False

		for osm_object in osm_addr_elements:
			if ("found" not in osm_object
					and "addr:housenumber" in osm_object['tags']
					and osm_object['tags']['addr:housenumber'].replace(" ", "").upper() == lm_addr['tags']['addr:housenumber']):

				distance = compute_distance(lm_addr['point'], (osm_object['lon'], osm_object['lat']))
				if distance < best_distance:
					keep_object = osm_object
					best_distance = distance
					found = True

		# Output new addr node to file if no match, or modified addr node if close location match
		
		new_object = {
			'type': 'node',
			'lat': lm_addr['point'][1],
			'lon': lm_addr['point'][0],
			'tags': lm_addr['tags']
		}

		if found:
			if keep_object['id'] in parents:
				keep_object['tags'] = {}
				generate_element (keep_object, action="modify")  # Keeo empty node if parents
				modified += 1

				generate_element (new_object, action="create")  # Create new addr node
				added += 1
			else:
				keep_object['tags'] = lm_addr['tags']
				keep_object['lat'] = lm_addr['point'][1]
				keep_object['lon'] = lm_addr['point'][0]
				generate_element (keep_object, action="modify")
				modified += 1

			keep_object['found'] = True

		else:
			generate_element (new_object, action="create")
			added += 1


	# 3rd pass:

	# Output copy of remaining, non-matched addr objects to file for manual inspection.
	# Delete remaining "clean" addr nodes (they did not match).
	# Remove addr tags from ways and relations (addr tags will be on separate addr nodes), except certain addr keys.

	for osm_object in osm_data['elements']:

		if "found" in osm_object:
			continue

		# Delete remaining "clean" address node (without other tags)

		if "clean" in osm_object:
			if osm_object['id'] in parents:
				osm_object['tags'] = {}
				generate_element (osm_object, action="modify")  # Keep empty node if parents
				modified += 1
			else:
				generate_element (osm_object, action="delete")
				deleted += 1

		# Delete "addr:" tags, except if "addr" is included in note=* and except certain addr tags (addr:door etc, see below).

		else:
			found_addr_tag = False
			found_other_tag = False
			found_note = False

			# Delete relevant addr tags, in case it is needed below

			new_tags = {}
			for tag in osm_object['tags']:

				if ((tag[0:5] == "addr:" or ":addr:" in tag)
						and tag not in ["addr:door", "addr:flats", "addr:floor"]
						and not (tag == "addr:housename" and osm_object['type'] != "node")):
					found_addr_tag = True

				elif "source" not in tag and tag != "created_by": 
					new_tags[ tag ] = osm_object['tags'][ tag ]
					if ("fixme" not in tag and "FIXME" not in tag
							and tag not in ["addr:door", "addr:flats", "addr:floot", "addr:housename"]):
						found_other_tag = True

			found_note = ("note" in osm_object['tags'] and "addr" in osm_object['tags']['note'])  # Opt-out note found

			# Remove address tags, unless opt-out note found

			if found_addr_tag and not found_note:
				if found_other_tag or osm_object['id'] in parents:
					osm_object['tags'] = new_tags
					generate_element (osm_object, action="modify")  # Keep nodes with parents
					removed += 1
				else:
					generate_element (osm_object, action="delete")
					deleted += 1
			else:
				generate_element (osm_object, action="output")  # No addr tag, or opt-out note found
				if found_note:
					remaining += 1

	# Report results

	message ("\r    ")
	message ("\tAddresses in cadastral source:         %i\n" % validated)
	message ("\tAdded new addresses:                   %i\n" % added)
	message ("\tUpdated existing addresses:            %i\n" % modified)
	message ("\tDeleted existing addresses:            %i\n" % deleted)
	message ("\tRemoved address tags:                  %i\n" % removed)
	message ("\tTotal changeset elements:              %i\n" % uploaded)
	message ("\tOther elements with addr tag in OSM:   %i\n" % remaining)



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



# Create XML roots, to be output later

def init_root():

	global osm_root		# XML of all addresses in municipality
	global upload_root	# XML to be uploaded to OSM
	global save_root 	# XML of all deleted addresses during run

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
			changeset_element.append(ET.Element("tag", k="source", v="Lantmäteriet Belägenhetsadress"))
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
			message ("\n\nCHANGESET TOO LARGE (%i) - UPLOAD MANUALLY WITH JOSM\n\n" % changeset_count)
			not_uploaded.append("%s %s" % (entity_id, entity_name))

	if not upload and changeset_count > 0 or upload and changeset_count >= 9900 or debug:
		osm_tree = ET.ElementTree(osm_root)
		indent_tree(osm_root)
		out_filename = "adresse_%s_%s.osm" % (entity_id, entity_name)
		out_filename = out_filename.replace(" ", "_")
		osm_tree.write(out_filename, encoding="utf-8", method="xml", xml_declaration=True)
		message ("Saved %i updates to file '%s'\n" % (changeset_count, out_filename))

	return False



# Load addresses and update OSM addresses with Lantmäteriet for one municipality

def process_municipality (municipality_id):

	global osm_data
	global osm_addr_index

	# Load addresses from Lantmäteriet and OSM

	start_time = time.time()
	message ("\n%s %s\n" % (municipality_id, municipalities[ municipality_id ]))

	load_lm_addresses(municipality_id)

	if not source:
		load_osm_addresses(municipality_id)
	else:
		osm_data = { 'elements': [] }
		osm_addr_index = {}

	# Match and merge

	merge_addresses(municipality_id)

	time_spent = time.time() - start_time
	message ("\nTime %i seconds\n" % time_spent)



# Main program

if __name__ == '__main__':

	total_start_time = time.time()
	message ("\n\n-- addr2osm v%s --\n" % version)

	# Load municipality and county codes/names

	municipalities = {}
	counties = {}
	load_municipalities()

	if len(sys.argv) > 1:
		entity = get_municipality(sys.argv[1])
	else:
		sys.exit ("Please provide name of municipality, county og 'Sverige' + optional '-upload' or '-source'\n\n")

	lm_token = get_lm_token()

	# Check OSM username/password

	source = ("-source") in sys.argv  # Only output LM source data
	upload = False
	if not source:
		upload = ("-upload" in sys.argv)
		if upload:
			osm_request_header = get_osm_token()

	# Process either one municipality or all municipalities in one county.
	# Uploading to OSM either per municipality or per county.

	osm_id = -1000
	not_uploaded = []  # Will contain counties/municipalities not uploaded due to changeset size
	uploaded = 0

	if len(entity) == 4:
		entity_name = municipalities[ entity ]
		init_root()
		process_municipality (entity)
		upload_changeset(entity, entity_name, uploaded)
		message ("\n")

	else:
		if entity == "00":
			entity_name = "Sweden (entire country)"
		else:
			entity_name = counties[entity]

		message ("Generating addresses for %s...\n" % entity_name)
		municipality_count = 0
		total_uploaded = 0

		for county_id in sorted(counties.keys()):
			if entity == "00" or county_id == entity:
				init_root()
				county_uploaded = 0

				for municipality_id in sorted(municipalities.keys()):
					if len(municipality_id) == 4 and municipality_id[0:2] == county_id and municipality_id >= first_municipality:
						process_municipality (municipality_id)
						total_uploaded += uploaded
						county_uploaded += uploaded
						municipality_count += 1

						if changeset_area == "municipality":
							upload_changeset(municipality_id, municipalities[ municipality_id ], uploaded)
							init_root()

				if changeset_area == "county" and county_uploaded > 0:
					message ("\n\n")
					upload_changeset(county_id, counties[ county_id ], county_uploaded)

		message ("\nDone processing %i municipalities in %s, %i changes\n" % (municipality_count, entity_name, total_uploaded))
		time_spent = time.time() - total_start_time
		message ("Total time %i:%02d minutes\n\n" % (time_spent / 60, time_spent % 60))

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
