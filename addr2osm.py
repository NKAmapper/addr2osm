#!/usr/bin/env python
# -*- coding: utf8

# ADDR2OSM.PY
# Loads addresses from Kartverket and creates an osm file with updates, alternatively uploads to OSM
# Usage: "python addr2osm.py <kommune/fylkesnummer> [-manual|-upload]""
# Creates "new_addresses_xxxx_xxxxxx.osm" file
# Optional "-manual" parameter will add DELETE tag instead of deleting node + include surplus addr objects
# Optional "-upload" parameter will ask for username/password and upload to OSM


import json
import urllib
import urllib2
import zipfile
import StringIO
import sys
import csv
import math
import time
import copy
from itertools import tee


version = "0.6.3"
debug = True
request_header = {"User-Agent": "addr2osm/" + version}

osm_api = "https://api.openstreetmap.org/api/0.6/"  # Production database
#osm_api = "https://master.apis.dev.openstreetmap.org/api/0.6/"  # Test database

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

def osm_tag (key, value, action):

	value = value.strip()
	if value:
		value = escape(value).encode('utf-8')
		key = escape(key).encode('utf-8')
		line = "    <tag k='%s' v='%s' />\n" % (key, value)
		
		if not(upload):
			file_out.write (line)
		elif action != "output":
			osm_upload ("  " + line)


# Generate one osm line

def osm_line (value):

	value = value.encode('utf-8')
	file_out.write (value)


# Open file/api, try up to 5 times, each time with double sleep time

def open_url (url):

	tries = 0
	while tries < 5:
		try:
			return urllib2.urlopen(url)
		except urllib2.HTTPError, e:
			if e.code in [429, 503, 504]:  # Too many requests, Service unavailable or Gateway timed out
				if tries  == 0:
					message ("\n") 
				message ("\rRetry %i... " % (tries + 1))
				time.sleep(5 * (2**tries))
				tries += 1
			elif e.code in [401, 403]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Unauthorized or Blocked
				sys.exit()
			elif e.code in [400, 409, 412]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Bad request, Conflict or Failed precondition
				message ("%s\n" % str(e.read()))
				sys.exit()
			else:
				raise
	
	message ("\nHTTP error %i: %s\n" % (e.code, e.reason))
	sys.exit()


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
						+ "Full match;Not full match;Corrected street names;New;Updated;Deleted;Remaining;Uploaded;Not uploaded;Time\n"
		file_log.write (output_text)
	elif ("action" in kwargs) and (kwargs['action'] == "close"):
		file_log.close()
	else:
		for data in args:
			if type(data) == unicode:
				file_log.write(data.encode('utf-8'))
			else:
				file_log.write(str(data))
			if not(("action" in kwargs) and (kwargs['action'] == "endline")):
				file_log.write(";")
		if ("action" in kwargs) and (kwargs['action'] == "endline"):
				file_log.write("\n")


# Output changeset line in OsmChange file format + maintain log file

def osm_upload (*args, **kwargs):

	global file_upload
	global changeset_data

	if ("action" in kwargs) and (kwargs['action'] == "open"):  # Opens file
		if debug:
			file_upload = open("upload_addr2osm.xml", "w")

	elif ("action" in kwargs) and (kwargs['action'] == "close"):  # Closes file
		if debug:
			file_upload.close()

	else:
		if type(args[0]) == unicode:
			line = args[0].encode('utf-8')
			changeset_data += line
			if debug:
				file_upload.write(line)
		else:
			changeset_data += args[0]
			if debug:
				file_upload.write(args[0])


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
	global uploaded
	global changeset_id

	if element:  # None if recurse down more than 1 level

		if upload and (action != "output"):
			osm_upload ("  <%s>\n" % action )

		if action == "create":  # Only nodes are created
			osm_id -= 1
			if upload:
				line = "    <node id='%i' changeset='%s' version='1' lat='%f' lon='%f'>\n" % (osm_id, changeset_id, element['lat'], element['lon'])
				osm_upload (line)
			else:
				line = "  <node id='%i' action='modify' visible='true' lat='%f' lon='%f'>\n" % (osm_id, element['lat'], element['lon'])
				osm_line ("  " + line)

		else:
			action_text = ""
			if action == "delete":
				if manual:
					element['tags']['DELETE'] = "yes"
				else:
					action_text = "action='delete' "
			elif action == "modify":
				action_text = "action='modify' "

			line = u"  <%s id='%i' %stimestamp='%s' uid='%i' user='%s' visible='true' version='%i' changeset='%i'"\
					% (element['type'], element['id'], action_text, element['timestamp'], element['uid'], escape(element['user']),\
					element['version'], element['changeset'])
			if element['type'] == "node":
				line_end = " lat='%f' lon='%f'>\n" % (element['lat'], element['lon'])
			else:
				line_end = ">\n"

			if not(upload):
				osm_line (line + line_end)
			elif action != "output":
				line = u"    <%s id='%i' changeset='%s' version='%i'" % (element['type'], element['id'], changeset_id, element['version'])
				osm_upload (line + line_end)

		if "nodes" in element:
			for node in element['nodes']:
				line = "    <nd ref='%i' />\n" % node
				if not(upload):
					osm_line (line)
				elif action != "output":
					osm_upload ("  " + line)

		if "members" in element:
			for member in element['members']:
				line = "    <member type='%s' ref='%i' role='%s' />\n" % (escape(member['type']), member['ref'], member['role'])
				if not(upload):
					osm_line (line)
				elif action != "output":
					osm_upload ("  " + line)

		if "tags" in element:
			for key, value in element['tags'].iteritems():
				osm_tag (key, value, action)  # Includes upload

		line = "  </%s>\n" % element['type']
		if not(upload):
			osm_line (line)
		elif action != "output":
			osm_upload ("  " + line)
			osm_upload ("  </%s>\n" % action )
			uploaded += 1

		# Recursively output child/member objects if any

		if manual or (action != "delete"):
			if "nodes" in element:
				for node in element['nodes']:
					osm_element (find_element(node), action="output")

			if "members" in element:
				for member in element['members']:
					osm_element (find_element(member['ref']), action="output")


# Process one municipality

def process_municipality (municipality_id):

	global file_out
	global osm_id
	global osm_children
	global changeset_id
	global changeset_data
	global uploaded

	start_time = time.time()

	# Load Norwegian municipality name for given municipality number from parameter

	if municipality_id == "1940":
		municipality_name = "Gaivuotna"
	elif municipality_id == "21":
		municipality_name = "Svalbard"
	else:
		file = open_url("https://ws.geonorge.no/kommuneinfo/v1/kommuner/" + municipality_id)
		municipality_data = json.load(file)
		file.close()
		municipality_name = municipality_data['kommunenavnNorsk'].replace(u"Æ","E").replace(u"Ø","O").replace(u"Å","A")\
													.replace(u"æ","e").replace(u"ø","o").replace(u"å","a")

	log (municipality_id[0:2], county[municipality_id[0:2]], municipality_id, municipality[municipality_id])

	# Load existing addr nodes in OSM for municipality

	message ("\nLoading existing addresses for %s %s from OSM Overpass... " % (municipality_id, municipality[municipality_id]))
	query = '[out:json][timeout:60];(area[ref=%s][admin_level=7][place=municipality];)->.a;(nwr[~"addr:"~".*"](area.a););out center meta;'\
			 % (municipality_id)
	if municipality_id == "21":
		query = query.replace("[ref=21][admin_level=7][place=municipality]", "[name=Svalbard][admin_level=4]")
	request = urllib2.Request("https://overpass-api.de/api/interpreter?data=" + urllib.quote(query), headers=request_header)
	file = open_url(request)
	osm_data = json.load(file)
	file.close()

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

	# Recurse down to get any childen

	if manual:
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

	# Open output files

	if upload:
		changeset_id = "ZZZZZZZZ"  # Dummy changeset id to be replaced before upload
		changeset_data = ""  # String which will contain changeset payload in osmChange xml format
		osm_upload(action="open")
		line = "<osmChange version='0.6' generator='addr2osm v%s'>\n" % version
		osm_upload(line)
	else:
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
	uploaded = 0

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
				tags = osm_object['tags']

				if (osm_object['pure']) and (housenumber == tags['addr:housenumber']) and (street == tags['addr:street'])\
					 and (postcode == tags['addr:postcode']) and (city == tags['addr:city']):

					found[checked] = True
					matched += 1
					distance = math.sqrt(((osm_object['lon'] - longitude)*(1.4416 - latitude*0.015719)) ** 2\
							 + (osm_object['lat'] - latitude) ** 2)  # Linear approximation

					# Modify object coordinates if it has been relocated. Keep the existing node if it has parents

					if (distance > 0.00001) or ('addr:country' in tags):

						if osm_object['id'] in parents:
							modify_object = copy.deepcopy(osm_object)
							modify_object['tags'] = {}
							osm_element (modify_object, action="modify")  # Keep empty node if parents
							modified += 1

							osm_object['lat'] = latitude
							osm_object['lon'] = longitude
							osm_object['tags'].pop('addr:country', None)
							osm_element (osm_object, action="create")  # Create new addr node
							added += 1

						else:
							osm_object['lat'] = latitude
							osm_object['lon'] = longitude
							osm_object['tags'].pop('addr:country', None)
							osm_element (osm_object, action="modify")
							modified += 1

					for index in street_index.itervalues():
						if index['from'] > found_index:
							index['from'] -= 1
						if index['to'] >= found_index:
							index['to'] -= 1

					del osm_data['elements'][found_index]  # Remove match to speed up looping later
					break

	# Report

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

	if upload:
		message ("\nCompleting changeset... ")
	else:
		message ("\nCompleting file %s..." % filename)

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
					if osm_object['clean']:

						distance = math.sqrt(((osm_object['lon'] - longitude)*(1.4416 - latitude*0.015719)) ** 2\
								 + (osm_object['lat'] - latitude) ** 2)  # Linear approximation

						if distance < 0.0001:
							keep_object = copy.deepcopy(osm_object)
							del osm_data['elements'][found_index]
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
						osm_element (keep_object, action="modify")  # Keeo empty node if parents
						modified += 1

						osm_element (modify_object, action="create")  # Create new addr node
						added += 1

					else:
						osm_element (modify_object, action="modify")
						modified += 1

				else:
					osm_element (modify_object, action="create")
					added += 1

	# 3rd pass:
	# Output copy of remaining, non-matched addr objects to file (candidates for manual deletion of address tags and potentially also addr nodes)
	# Delete remaining "clean" addr nodes (they got no match).
	# Remove addr tags from ways and relations except addr:housename (addr tags will be on separate addr nodes)

	for osm_object in osm_data['elements']:

		# Delete "pure" address node
		if osm_object['clean']:

			if osm_object['id'] in parents:
				keep_object = copy.deepcopy(osm_object)
				keep_object['tags'] = {}
				osm_element (keep_object, action="modify")  # Keep empty node if parents
				modified += 1
			else:
				deleted += 1
				osm_element (osm_object, action="delete")

		# Delete "addr:" tags for buildings, except "addr:housename" and POIs
		elif (manual or upload) and ("building" in osm_object['tags']):

			modify_object = copy.deepcopy(osm_object)
			found_addr_tag = False
			found_poi_tag = False
			for tag in osm_object['tags']:
				if (tag[0:5] == "addr:") and (tag != "addr:housename"):
					modify_object['tags'].pop(tag)
					found_addr_tag = True
				elif (tag in ["amenity", "leisure", "tourism", "shop", "office", "craft", "club"]):
					found_poi_tag = True

			if found_addr_tag and not(found_poi_tag):
				osm_element (modify_object, action="modify")
			else:
				osm_element (osm_object, action="output")

		elif manual:
			osm_element (osm_object, action="output")

	file_in.close()

	# Report

	message ('\n')
	message ('  New addresses:                            %i\n' % added)
	message ('  Updated existing address nodes:           %i\n' % modified)
	message ('  Deleted existing address nodes:           %i\n' % deleted)
	message ('  Total changeset elements:                 %i\n' % uploaded)
	message ('  Remaining addresses in OSM without match: %i\n' % (len(osm_data['elements']) - deleted))

	# Upload changeset

	uploaded_result = 0

	if upload:
		osm_upload ("</osmChange>")

		if uploaded > 0:
			if uploaded < 9900:  # Maximum upload is 10.000 elements

				today_date = time.strftime("%Y-%m-%d", time.localtime())
				changeset_xml = "<osm> <changeset> <tag k='created_by' v='addr2osm v%s' /> " % version
				changeset_xml += "<tag k='comment' v='Address import for %s' /> " % municipality[municipality_id]
				changeset_xml += "<tag k='source' v='Kartverket Matrikkelen Vegadresse' /> "
				changeset_xml += "<tag k='source:date' v='%s' /> </changeset> </osm>" % today_date
				changeset_xml = changeset_xml.encode('utf-8')

				request = urllib2.Request(osm_api + "changeset/create", data=changeset_xml, headers=osm_request_header)
				request.get_method = lambda: 'PUT'
				file = open_url(request)  # Create changeset
				changeset_id = file.read()
				file.close()		

				message ("\nUploading %i elements to OSM in changeset #%s..." % (uploaded, changeset_id))

				changeset_data = changeset_data.replace("ZZZZZZZZ", changeset_id)
				request = urllib2.Request(osm_api + "changeset/%s/upload" % changeset_id, data=changeset_data, headers=osm_request_header)
				file = open_url(request)  # Write changeset in one go
				file.close()

				request = urllib2.Request(osm_api + "changeset/%s/close" % changeset_id, headers=osm_request_header)
				request.get_method = lambda: 'PUT'
				file = open_url(request)  # Close changeset
				file.close()

				uploaded_result = uploaded
				uploaded = 0
			else:
				message ("\n\nCHANGESET TOO LARGE (%i) - UPLOAD MANUALLY\n\n" % uploaded)

		osm_upload (action="close")  # Close log files

	else:
		osm_line ("</osm>")
		file_out.close()

	# Report time used

	time_spent = time.time() - start_time
	message ('\nTime %i seconds (%i addresses per second)\n\n' % (time_spent, validated / time_spent))

	log (added, modified, deleted, len(osm_data['elements']) - deleted, uploaded_result, uploaded)
	log (int(time_spent), action="endline")


# Main program

if __name__ == '__main__':

	global manual

	total_start_time = time.time()
	message ("\n-- addr2osm v%s --\n" % version)

	if (len(sys.argv) == 2) and (len(sys.argv[1]) in [2,4]) and sys.argv[1].isdigit():
		entity = sys.argv[1]
		manual = False
		upload = False
	elif (len(sys.argv) == 3) and (len(sys.argv[1]) in [2,4]) and sys.argv[1].isdigit() and (sys.argv[2] in ["-manual", "-upload"]):
		entity = sys.argv[1]
		if sys.argv[2] == "-manual":
			manual = True
			upload = False
		elif sys.argv[2] == "-upload":
			manual = False
			upload = True
		else:
			manual = False
			upload = False
	else:
		sys.exit ('Usage: Please type "python addr2osm.py <nnnn>" with 4 digit municipality number or 2 digit county number\n'\
					+ '       Add "-manual" to get surplus address objects and DELETE tag\n'\
					+ '       Add "-upload" to automatically upload changes to OSM\n')

	# Check OSM username/password

	if upload:
		message ("This program will automatically upload adress changes to OSM\n")
		username = raw_input ("Please enter OSM username: ")
		password = raw_input ("Please enter OSM password: ")

		authorization = username.strip() + ":" + password.strip()
		authorization = "Basic " + authorization.encode('base64')[:-2]  # Omit newline
		osm_request_header = request_header
		osm_request_header.update({'Authorization': authorization})

		request = urllib2.Request(osm_api + "permissions", headers=osm_request_header)
		file = open_url(request)
		permissions = file.read()
		file.close()

		if permissions.find("allow_write_api") < 0:  # Authorized to modify the map
			sys.exit ("Wrong username/password or not authorized\n")

	# Load municipality id's and names from Kartverket api

	message ("Loading municipality and county codes from Kartverket\n")
	file = open_url("https://ws.geonorge.no/kommuneinfo/v1/kommuner")
	municipality_data = json.load(file)
	file.close()

	municipality = {}
	for mun in municipality_data:
		municipality[mun['kommunenummer']] = mun['kommunenavn'].strip()
	municipality['21'] = "Svalbard"

	# Load county id's and names from Kartverket api

	file = open_url("https://ws.geonorge.no/kommuneinfo/v1/fylker")
	county_data = json.load(file)
	file.close()

	county = {}
	for coun in county_data:
		county[coun['fylkesnummer']] = coun['fylkesnavn'].strip()
	county['21'] = "Svalbard"

	# Load corrections from Github

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

		message ("Generating addresses for %s...\n" % entity_name)
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
		
