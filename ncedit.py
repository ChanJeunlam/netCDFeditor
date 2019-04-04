#!/usr/bin/python3

editorhelp = """
Class EditNetCDF

This class takes an input netCDF file and creates a python dictionary
structure that mimics that of the input netCDF [<instance>.structure]. 

This structure is placed inside another dictionary [<instance>.template]
that is taken as the third argument to the EditNetCDF.Update function. 

The UpdateHeader function takes three arguments: a source netCDF object 
open in read mode, a destination netCDF object open in write mode, and 
the template dictionary mentioned above. 

Dimensions, variables, groups, and attributes from the source netCDF are 
copied to the output netCDF. Any changes to the input template are
applied during the copy:

* rename any dimension, variable, or group
* rename any attribute; change any attribute value
* change the fill value for any data variable (data; not just attribute)

Some other important info:

* any elements deleted from the 'header' element of the json template
  will be left alone during copy
* the 'updates' element of the json template has a translation table 
  named 'rename' that maps source names to destination names. ONLY 
  CHANGE NAMES IN THIS SECTION. Leave the names in the 'header' section
  alone. They are used to access the data while copying. 

Version 0. Tested on ~two dozen files. Needs more type checking of inputs
and edge case checking for netCDF structures, e.g. nested groups.

All the functions run independently, without class instantiation.
"""

import os
import sys
import glob
import json
import cftime
import argparse
import numpy as np
import netCDF4 as nc4
from collections import OrderedDict

""" --------------------------------------------------------------------------
Editor class
 --------------------------------------------------------------------------"""


class EditNetCDF(object):
	"""{f}""".format(f=editorhelp)
		

	def __getitem__(self, name):
		return getattr(self, name)
	

	def __init__(self, f=None):
		"""Arguments: f==netCDF file."""
		self.f = f
		self.nc = self.GetNC(self.f)
		if self.nc:
			self.structure = self.GetStructure(self.nc)
			self.template = self.GetTemplate(self.structure)
	
			
	@staticmethod
	def GetNC(f, mode="r"):
		"""Handles netCDF read failures gracefully."""
		try:
			nc = nc4.Dataset(f, mode)
			return(nc)
		except: 
			print("Failed to read netCDF: "+str(f))
		

	@staticmethod
	def GetStructure(nc):
		"""Makes a JSON ( Panoply-like ) representation of netCDF structure."""
		s = {'dimensions': {}, 'variables': {}, 'groups': {}, 'attributes': {}}

		# add dimensions to structure
		s['dimensions'].update({
			name: "UNLIMITED" if dim.isunlimited() else dim.size
		for name, dim in nc.dimensions.items()})

		# add variables to structure
		s['variables'].update({name: {
			'dimensions': var.dimensions, 
			'attributes': {att: fmt(getattr(var, att)) for att in var.ncattrs()}	
		} for name,var in nc.variables.items()})

		# add grouped variables to structure
		for name, grp in nc.groups.items():

			# get group variables
			variables = {name: {
				'dimensions': var.dimensions, 
				'attributes': {att: fmt(getattr(var, att)) for att in var.ncattrs()}
			} for name,var in grp.variables.items()}

			# get group attributes
			attributes = {att: fmt(getattr(name, att)) for att in grp.ncattrs()}

			# add group to structure
			s['groups'][name] = {'variables': variables, 'attributes': attributes}

		# add global attributes to structure
		s['attributes'].update(
			{att: fmt(getattr(nc, att)) for att in nc.ncattrs()})

		return(s)


	@staticmethod
	def GetTemplate(structure):
		"""Returns the complete EditNetCDF template as json string."""
		s = structure

		# get lists of rename-able netCDF elements
		dimensions = list(s['dimensions'].keys())
		variables = list(s['variables'].keys())
		groups = list(s['groups'].keys())
		for g in groups:
			variables.extend(list(s['groups'][g]['variables'].keys()))
		
		structure = OrderedDict([
			("header", s),
			("updates", {
				'rename': {
					"dimensions": {d:d for d in dimensions},
					"variables": {v:v for v in variables},
					'groups': {g:g for g in groups}},
				"permute": {
					"list_variables_invert_y": [],	
					"list_variables_invert_x": []},
				"applyfuncx": {v:[] for v in variables},
				"compression_level": 4
			})
		])

		# combine with other template pieces and return
		return(structure)
		

	@staticmethod
	def UpdateHeader(src, dst, ud):
		"""
		"""

		# get renaming translation table from template
		updates = ud['updates']
		rename = updates['rename']
		compress = updates['compression_level']
		structure = ud['header']
			
		# copy global attributes all at once via dictionary
		dst.setncatts(structure['attributes'])
		
		# copy dimensions
		for name, dimension in src.dimensions.items():
			newname = rename['dimensions'][name]
			size = (len(dimension) if not dimension.isunlimited() else None)
			dst.createDimension(newname, size)
		
		# copy all variables
		for name, variable in src.variables.items():
			newname = rename['variables'][name]
			attributes = structure['variables'][name]['attributes']

			modifiers, applyfuncs = get_modifiers(name, updates)

			# fill array with new fill value if exists; make output var
			vdata = edit_variable(variable, attributes, modifiers, applyfuncs)
			dst.createVariable(
				newname, variable.datatype, variable.dimensions,
				zlib=True, complevel=compress, fill_value=vdata[1])
			dst[newname].setncatts(vdata[2])

			# add array
			dst[newname][:] = vdata[0]

		# copy all groups
		for name, group in src.groups.items():
			gnewname = rename['groups'][name]
			
			# make group in output file
			dst.createGroup(gnewname)
			
			# copy all group variables
			for vname, variable in group.variables.items():
				vnewname = "/"+gnewname+"/"+rename['variables'][vname]
				vattributes = structure['variables'][name]['attributes']

				modifiers, applyfuncs = get_modifiers(vname, updates)

				# fill array with new fill value if exists; make output var
				vdata = edit_variable(variable, vattributes, modifiers, applyfuncs)
				dst.createVariable(
					vnewname, variable.datatype, variable.dimensions,
					zlib=True, complevel=compress, fill_value=vdata[1])
				dst[vnewname].setncatts(vdata[2])

				# add array
				dst[vnewname][:] = vdata[0]

		# close both files
		src.close()
		dst.close()


# ----------------------------------------------------------------------------
# editor helpers
# ----------------------------------------------------------------------------

modifierfuncs = { #"list_pairs_variable_applyfunc": [],
	"list_variables_invert_y": np.flipud,
	"list_variables_invert_x": np.fliplr,
	"list_invert_1d": print}


def get_modifiers(variable_name, updates_dict):
	""" """
	m = []
	for modifier, variables in updates_dict['permute'].items():
		if variable_name in variables:
			m.append(modifierfuncs[modifier])
	fx = updates_dict['applyfuncx'][variable_name]
	return(m, fx)


def edit_variable(variable, attributes, modifiers, applyfuncs):
	"""Checks for fill value and applies to output array if it exists."""
	data = variable[:]
	if modifiers:
		for m in modifiers:
			data = m(data)

	if applyfuncs:
		for fx in applyfuncs:
			func = eval("lambda x: "+fx)
			try:
				data = func(data)
			except:
				print("Function "+fx+" applied to variable ADD THIS JACK did not evaluate correctly. Skipping.")

	if "_FillValue" in attributes.keys():
		fill = attributes['_FillValue']
		srcfill = variable.__dict__['_FillValue']
		data[data==srcfill] = fill
		del attributes['_FillValue']
	else:
		fill=None
	return((data,fill,attributes))


def fmt(obj, strings = False): 
	"""Value formatter replaces numpy types with base python types."""
	if strings: 
		out = str(obj)
	if isinstance(obj, (str, int, float, complex, tuple, list, dict, set)):
		out = obj
	else:
		try:
			out = obj.item()
		except:
			out = obj.tolist()
	return(out)


objnone = "\t. No {t} {n} found in input template: {j}. Skipping."

# ----------------------------------------------------------------------------
# script mode functions
# ----------------------------------------------------------------------------


def args_parser():
	"""Args_handler: argument parsing for editnc.py."""

	p = argparse.ArgumentParser(description="""I will write some help here.""",
		formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	p.add_argument("fin", nargs='?', default=os.getcwd(), help="Input dir (wildcard optional) / netCDFs")
	p.add_argument("--json", "-js", nargs="?", help="Edit input netCDF(s) using input JSON template")
	
	return(p)


if __name__ == '__main__':
	
	# handle arguments, validate
	p = args_parser()
	args = p.parse_args()

	if os.path.isfile(args.fin):
		filelist = [args.fin]
	elif os.path.isdir(args.fin):
		filelist = glob.glob(args.fin+"/*.nc*")
		if len(filelist)<1:
			print("No files netCDF files found: "+str(args.fin))
	else: 
		sys.exit("Invalid argument 1: "+str(args.fin))

	if args.json is None:			
		for f in filelist:
		
			# initialize editor
			editor = EditNetCDF(f)

			# write template to json
			try:
				fout = os.path.splitext(os.path.basename(f))[0] +".json"
				with open(fout, "w") as j:
					json.dump(editor.template, j, indent=4)
			except:
				print("No JSON written for netCDF: "+os.path.basename(f))

	else:
		if os.path.isfile(args.json): 	
			try:
				with open(args.json, "r") as j:
					ud = json.load(j)
			except Exception as e:
				print("Invalid argument 2: "+str(args.json))
				raise(e)

		for f in filelist:

			# output filename equal to "<filename>_edit.nc"
			fn = os.path.splitext(os.path.basename(f))
			fout = fn[0] +"_edit"+ fn[1]

			# open input and output; pass to updater
			ncin = EditNetCDF.GetNC(f)
			ncout = EditNetCDF.GetNC(fout, mode="w")
			EditNetCDF.UpdateHeader(ncin, ncout, ud)

	