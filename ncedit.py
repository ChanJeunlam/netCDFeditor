#!/usr/bin/python3


import sys
import glob
import json
import argparse
import numpy as np
import netCDF4 as nc4
from collections import OrderedDict
from os.path import join, isfile, isdir, basename, splitext

""" --------------------------------------------------------------------------
Editor class
 --------------------------------------------------------------------------"""


class EditNetCDF(object):
	"""
	Takes an input netCDF file and creates a python dictionary structure that 
	mimics the structure of the input netCDF [<instance>.structure]. This 
	structure is placed inside another dictionary [<instance>.template] that 
	has a few other options for manipulating the data written to the output
	netCDF. The template is passed as the third argument to the Update function. 
	"""
		

	def __getitem__(self, name):
		return getattr(self, name)
	

	def __init__(self, nc=None, updates=None, out=None):	
		self.nc = nc
		self.out = out
		self.updates = updates

		# if: all args passed, run Updater
		if all([updates,out]):

			# get updates options from updates element of dict
			self.rename = self.updates['updates']['rename']
			self.permute = self.updates['updates']['permute']
			self.funcx = self.updates['updates']['funcx']
			self.compress = self.updates['updates']['compression_level']

			# get structure from header element of dict
			self.structure = self.updates['header']

			# write changes to output netCDF
			self.Updater()

			# close both files
			self.nc.close()
			self.out.close()
		
		# else if: no args passed, generate structure/template
		elif not any([updates,out]):
			self.structure = self.GetStructure(self.nc)
			self.template = self.GetTemplate(self.structure)

		# else: reserve this condition for custom inputs in the future
		else:
			print("Execute some custom functionalities. In the future.")
		

	# ------------------------------------------------------------------------
	# static methods, fully functionsl without class instantiation


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
					"variables2d_yflip": [],	
					"variables2d_xflip": [],
					"variables1d_flip": []},
				"funcx": {v:[] for v,d in s['variables'].items()},
				"compression_level": 4
			})
		])

		# combine with other template pieces and return
		return(structure)
	

	# ------------------------------------------------------------------------
	# array manipulation


	def GetModifiers(self, name, funcs=[]):
		for modifier, variables in self.permute.items():
			if name in variables:
				funcs.append({
					"variables2d_yflip": np.flipud,
					"variables2d_xflip": np.fliplr,
					"variables1d_flip": np.flip
				}[modifier])
		return(funcs)


	def ApplyFuncs(self, data, funcs):
		"""Internal use. Takes input data and list of string funcs and apply."""
		for f in funcs:
			try:
				func = eval("lambda x: "+f)
				data = func(data)
			except:
				print("Function "+f+" did not evaluate correctly. Skipping.")
		return(data)


	# ------------------------------------------------------------------------
	# updaters


	def Updater(self):
		"""
		"""

		# add global attributes
		self.UpdateGlobalAtts()

		# add dimensions
		self.UpdateDims()

		# add root-group (ungrouped) variables
		self.UpdateVars(self.nc.variables)

		# add grouped variables
		self.UpdateGroups()


	def UpdateGlobalAtts(self):
		"""Internal use. Copy global attributes all at once via dictionary."""
		self.out.setncatts(self.structure['attributes'])


	def UpdateDims(self):
		"""Internal use. Create new dimensions in output netCDF."""
		for name, dimension in self.nc.dimensions.items():
			newname = self.rename['dimensions'][name]
			size = (len(dimension) if not dimension.isunlimited() else None)
			self.out.createDimension(newname, size)


	def UpdateVars(self, variables, nameprefix=None):
		"""Internal use. Copy/edit variables on their way to output netCDF."""
		for name, variable in variables.items():
			if nameprefix:
				newname = nameprefix+self.rename['variables'][name]
			else:
				newname = self.rename['variables'][name]
			
			data = variable[:]
			attributes = self.structure['variables'][name]['attributes']

			# apply numpy array modifiers
			npfuncs = self.GetModifiers(name)
			if npfuncs:
				for f in npfuncs:
					data = f(data)
			# apply functionx user arithmetic funcs
			strfuncs = self.funcx[name]
			if strfuncs:
				data = self.ApplyFuncs(data, strfuncs)

			# apply fill value if it exists
			if "_FillValue" in attributes.keys():
				fill = attributes['_FillValue']
				srcfill = variable.__dict__['_FillValue']
				data[data==srcfill] = fill
				del attributes['_FillValue']
			else:
				fill=None

			# finally, make output variable
			self.out.createVariable(
				newname, variable.datatype, variable.dimensions,
				zlib=True, complevel=self.compress, fill_value=fill)
			self.out[newname].setncatts(attributes)
			self.out[newname][:] = data


	def UpdateGroups(self):
		"""Internal use. Copy/edit grouped variables to output netCDF."""
		for name, group in self.nc.groups.items():
			newname = self.rename['groups'][name]
			
			# make group in output file
			self.out.createGroup(newname)

			# a prefix to add to variable names
			nameprefix = "/"+newname+"/"

			# add variables to group
			self.UpdateVars(group.variables, nameprefix=nameprefix)


def fmt(obj): 
	"""Value formatter replaces numpy types with base python types."""
	if isinstance(obj, (str, int, float, complex, tuple, list, dict, set)):
		out = obj
	else:
		try:
			out = obj.item()
		except:
			out = obj.tolist()
	return(out)


# ----------------------------------------------------------------------------
# script mode functions
# ----------------------------------------------------------------------------

bugnotice = "You found a bug. Please tell Jack."
getfout = lambda f,p2,tail: join(p2, splitext(basename(f))[0]+tail)


def rw_handler(f, mode="r"):
	"""Handles netCDF read failures gracefully. Also opens for writing."""
	try:
		nc = nc4.Dataset(f, mode)
	except: 
		print("Failed to read netCDF: "+str(f))
		nc = None
	return(nc)


def template_mode(nc, jsout, *args):
	"""Called when two arguments received. Writes json templates."""
	editor = EditNetCDF(nc)
	try:
		with open(jsout, "w") as j:
			json.dump(editor.template, j, indent=4)
	except:
		print("Error>Failed to write JSON template for: "+basename(f))


def editor_mode(ncin, fileout, js):
	"""Called when three arguments received. Writes edited netCDFs."""
	
	# read input json template
	try:
		with open(js, "r") as j:
			ud = json.load(j)
	except:
		sys.exit(print("Error>Failed to read JSON: "+str(js)+". Exit."))

	# open output netCDF
	ncout = rw_handler(fileout, mode="w")

	# apply changes via EditNetCDF
	EditNetCDF(ncin, ud, ncout)


def args_parser():
	"""Args_handler: argument parsing for editnc.py."""

	p = argparse.ArgumentParser(
		description="""I will write some help here.""",
		formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	p.add_argument("in_path", 
		help="Input netCDF OR directory with netCDFs; optional wildcard.")
	p.add_argument("out_path", 
		help="Output directory to write netCDFs.")
	p.add_argument("in_json", nargs="?", default=None, help="Input JSON template.")

	args = p.parse_args()

	### CHECK OPTIONAL ARGUMENT 3
	j = args.in_json
	if j:
		tail = "_edit.nc"
		mode = editor_mode
	else:
		tail = ".json"
		mode = template_mode

	### CHECK ARGUMENTS 1 AND 2
	p1, p2 = args.in_path, args.out_path
	
	# if argument 1 is neither a file nor a path, raise e; 
	if not any([isfile(p1), isdir(p1)]):
		sys.exit(print("Invalid file/path passed to arg 1. Exiting."))
	
	# same for 2;
	elif not any([isfile(p2), isdir(p2)]):
		sys.exit(print("Invalid file/path passed to arg 2. Exiting."))
	
	# if arg 1 is a dir, arg 2 must also be a dir
	elif all([isdir(p1), isfile(p2)]):
		sys.exit(print("Arg 2 must be directory if arg 1 is a directory."))
		
	# if arg 1 is a file and arg 2 is a dir
	elif all([isfile(p1), not isdir(p2)]):
		jobs = [(p1, p2, j)]

	# else glob p1, append _edit to outputs
	else:
		in_files = [f for f in glob.glob(p1) if "nc" in splitext(f)[1]]
		if len(in_files) == 0:
			sys.exit(print("No input netCDF(s) at:"+str(p1)))

		# get jobs (tuples of input, output pairs)
		jobs = [(f, getfout(f, p2, tail), j) for f in in_files]

	# return two values: list of jobs (tuples) and mode function 
	return(jobs, mode)


if __name__ == '__main__':
	
	# handle arguments, validate
	jobs, mode = args_parser()
		
	for j in jobs:
		
		# open input netCDF
		nc = rw_handler(j[0])

		# pass to job function
		mode(nc, j[1], j[2])