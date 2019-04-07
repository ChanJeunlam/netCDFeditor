#!/usr/bin/python3
"""Notes:
* Add CRS variable generator
"""

import re
import sys
import glob
import json
import shutil
import argparse
import numpy as np
import netCDF4 as nc4
import datetime as dt
from collections import OrderedDict
from os.path import join, isfile, isdir, basename, splitext


# ----------------------------------------------------------------------------
# Some random stuff
# ----------------------------------------------------------------------------

# regular expression for validating input CF units for time
timeunitsre = re.compile(
    ".* since [0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1])"
    ".*(2[0-3]|[01][0-9]):[0-5][0-9]:[0-5][0-9].*")

def fmt(obj): 
    """Value formatter replaces numpy types with base python types."""
    if isinstance(obj, (str, int, float, complex, tuple, list, dict, set)):
        out = obj
    else:                        # else, assume numpy
        try:
            out = obj.item()     # try to get value
        except:
            out = obj.tolist()   # except, must be np iterable; get list
    return(out)

def GetTimeUnits(structure):
    """Gets the value of variable time's 'units' attribute."""
    try:
        units = structure["variables"]["time"]["attributes"]["units"]
        if timeunitsre.fullmatch(units):
            return(units)
        else:
            return(None)
    except:
        print("WARN: Unable to get units for variable time.")
        return(None)

def GetDimensions(nc):
    """Returns a dictionary describing the dimensions in a netCDF file."""
    return({name: {
        "size": dim.size, "UNLIMITED": True} if dim.isunlimited() else {
        "size": dim.size, "UNLIMITED": False}
    for name, dim in nc.dimensions.items()})

def GetVariables(nc):
    """Returns a dictionary describing the variables in a netCDF file."""
    return({name: {
        'dimensions': var.dimensions, 
        'attributes': {att:fmt(getattr(var,att)) for att in var.ncattrs()}
    } for name,var in nc.variables.items()})

def GetGroups(nc):
    """Returns a dictionary describing the groups in a netCDF file."""
    return({name: {
        'variables': GetVariables(grp), 
        'attributes': {att:fmt(getattr(name,att)) for att in grp.ncattrs()}
    } for name, grp in nc.groups.items()})

def GetAttributes(nc):
    """Returns a dictionary describing the attributes in a netCDF file."""
    return({att: fmt(getattr(nc, att)) for att in nc.ncattrs()})

def GetStructure(nc):
    """Makes a JSON (Panoply-like) representation of netCDF structure."""
    return({
        'dimensions': GetDimensions(nc), 
        'variables': GetVariables(nc), 
        'groups': GetGroups(nc), 
        'attributes': GetAttributes(nc)})


# ----------------------------------------------------------------------------
# Templater
# ----------------------------------------------------------------------------


def GetTemplate(nc):
    """Returns the complete EditNetCDF template as json string."""

    # get structure, lists of netCDF object names to make rename table
    s = GetStructure(nc)
    dimensions = list(s['dimensions'].keys())
    groups = list(s['groups'].keys())
    variables = list(s['variables'].keys())+[
        s['groups'][g]['variables'].keys() for g in groups]

    return(OrderedDict([
        ("header", s),
        ("updates", OrderedDict([
            ("drop", []),
            ("rename", {
                "dimensions": {d:d for d in dimensions},
                "variables": {v:v for v in variables},
                "groups": {g:g for g in groups}}),
            ("time", OrderedDict([
                ("in_origin", GetTimeUnits(structure)), 
                ("out_origin", None), 
                ("time_bnds_offset", None)])),
            ("permute", OrderedDict([
                ("variables1d_flip", []), 
                ("variables2d_xflip", []), 
                ("variables2d_yflip", [])])),
            ("funcx", {v:[] for v,d in s['variables'].items()}),
            ("compression_level", 4)
        ]))
    ]))


# ----------------------------------------------------------------------------
# Editor
# ----------------------------------------------------------------------------

def ApplyFuncs(data, funcs):
    """Takes input data and list of str funcs; evals; applies."""
    for f in funcs:
        try:
            func = eval("lambda x: "+f)
            data = func(data)
        except Exception as e:
            print("Function "+f+" did not evaluate correctly:")
            print(e)
            print("Skipping.\n"+"-"*79)
    return(data)

def GenerateTimeBnds(netcdf_object, offset):
    """Takes input array and generates array of tuples."""
    try:
        time = ncin.variables['time'][:]
        return(np.array(list(zip(time-offset, time+offset))))
    except:
        print("ERROR: Can't find time variable. Can't gen time_bnds.")
        return(None)


class EditNetCDF(object):
    """The big kahuna."""

    def __init__(self, ncin=None, ncout=None, template=None):    
        self.ncin = ncin
        self.ncout = ncout
        self.template = template
           
        # get structure from header element of dict
        self.structure = self.template['header']
            
        # get updates options from updates element of template
        self.drop = self.template['updates']['drop']
        self.rename = self.template['updates']['rename']
        self.time = self.template['updates']['time']
        self.permute = self.template['updates']['permute']
        self.funcx = self.template['updates']['funcx']
        self.compress = self.template['updates']['compression_level']

        # write all changes to output netCDF
        self.Updater()

    def __getitem__(self, name):
        return getattr(self, name)
        
    # ------------------------------------------------------------------------
    # updaters


    def Updater(self):
        """Goes through update routine."""
        # add global attributes
        self.WriteGlobalAttributes()

        # add dimensions
        self.WriteDimensions()

        # add root-group (ungrouped) variables; skip if in drop list
        for name, variable in self.ncin.variables.items():           
            if name not in self.drop:
                self.UpdateVariable(name, variable)

        # add grouped variables
        for name, group in self.ncin.groups.items():
            self.UpdateGroup(name, group)       

        # handle other miscellaneous updates
        #self.UpdatesMisc()


    # def UpdateMisc(self):
    #     """Random updates triggered by user input."""

    #     # add/update time_bnds if user says so
    #     if self.time["time_bnds_offset"]:
    #         offset = self.time["time_bnds_offset"]
    #         time_bnds = GenerateTimeBnds(self.ncin, offset)
    #         try:
    #             if "time_bnds" in self.ncin.variables:
    #                 self.ncin.variables["time_bnds"] = time_bnds
    #             else:
    #                 self.WriteVariable( 
    #                     self, name, dimensions, {
    #                         "time": "days since 1980-01-01 00:00:00 UTC"
    #                     }, dtype=None, 
    #                     data=None, fill=None, prefix=None)
    

    def UpdateArray(self, name, variable, fill=None):
        """Internal use. Edit input array."""

        # get input netCDF variable's underlying numpy array
        data = variable[:]

        # if fill value is supplied, try to get old fill value
        if fill:
            try:
                srcfill = variable.__dict__['_FillValue']
                data[data==srcfill] = fill   # replace srcfill with fill
            except:
                print(name+": no _FillValue in src netCDF; no fill replace.")

        # get built-in numpy array modifiers; apply
        npfuncs = self.GetModifiers(name)
        if npfuncs:
            for f in npfuncs:
                try:
                    data = f(data)
                except Exception as e:
                    print("Failed to apply permute: "+str(f)+". Skipping.")
                    print(e)

        # apply updates['funcx'] user-defined string funcs
        strfuncs = self.funcx[name]
        if strfuncs:
            data = ApplyFuncs(data, strfuncs)

        return(data)


    def UpdateVariable(self, name, variable):
        """Internal use. Copy/edit variable to output netCDF."""

        # get template variables for group; get dimensions, attributes
        template = self.structure['variables'][name]
        attributes = template['attributes']
        dimensions = template['dimensions']

        # get and drop fill from output attributes, if exists
        if '_FillValue' in attributes.keys():
            fill = attributes['_FillValue']
            del attributes['_FillValue']
        else:
            fill = None

        # update data array to reflect changes specified in template
        data = self.UpdateArray(name, variable, fill=fill)

        # add variable to output netCDF
        self.WriteVariable(
            name, dimensions, attributes, 
            dtype=variable.datatype, data=data, fill=fill)


    def UpdateGroup(self, name, group):
        """Internal use. Copy/edit grouped variables to output netCDF."""

        # get template variables for group
        variables = self.structure['groups'][name]

        # get new (or old) group name from input json
        groupname = self.rename['groups'][name]
        
        # make group in output file
        self.ncout.createGroup(groupname)

        # a prefix will be added to variable names; netCDF4-python req
        nameprefix = "/"+groupname+"/"

        # iterate over group's variables in input netCDF
        for variablename, variable in group.items():

            # get input netCDF variable data type
            dtype = variable.datatype

            # get dimensions, attributes given in template
            attributes = variables[variablename]['attributes']
            dimensions = variables[variablename]['dimensions']

            # get and drop fill from output attributes, if exists
            if '_FillValue' in attributes.keys():
                fill = attributes['_FillValue']
                del attributes['_FillValue']
            else:
                fill = None

            # update data array to reflect changes specified in template
            data = self.UpdateArray(name, variable, fill=fill)

            # add variable to output netCDF group
            self.WriteVariable(
                variablename, dimensions, attributes, 
                dtype=dtype, data=data, fill=fill, prefix=nameprefix)


    # use byte dtype for default (testing add vars not in source netCDF)
    def WriteVariable( 
        self, name, dimensions, attributes, 
        dtype=None, data=None, fill=None, prefix=None):
            """Adds variable to output netCDF."""
            
            # get rename (or old name, whatever); add prefix if group
            try:
                newname = self.rename['variables'][name]
                if prefix:
                    newname = prefix+newname
            except:
                print("INFO: Output variable "+name+" has no rename entry.")
                newname = name

            # make output variable; add attributes;
            try:                
                self.ncout.createVariable( 
                    newname, dtype, dimensions, zlib=True, 
                    complevel=self.compress, fill_value=fill)
                self.ncout[newname].setncatts(attributes)
                self.ncout[newname][:] = data

            except Exception as e:
                print("WARNING: Failed to write variable: "+newname)
                print(e)
                print("Skipping.\n"+"-"*79)


    def WriteGlobalAttributes(self):
        """Internal use. Copy global attributes all at once via dictionary."""
        self.ncout.setncatts(self.structure['attributes'])


    def WriteDimensions(self):
        """Internal use. Create new dimensions in output netCDF."""

        # iterate over input dimensions. check template for rename
        for name, dimension in self.ncin.dimensions.items():
            newname = self.rename['dimensions'][name]
            
            # None if dim['UNLIMITED'] is true in input template; else size
            if self.structure["dimensions"][name]["UNLIMITED"]:
                size = None
            else:
                size = len(dimension)
            
            # create dimension in output file
            self.ncout.createDimension(newname, size)

            
  # ------------------------------------------------------------------------
    # array modifiers


    def GetModifiers(self, name, funcs=[]):
        for modifier, variables in self.permute.items():
            if name in variables:
                funcs.append({
                    "variables2d_yflip": np.flipud,
                    "variables2d_xflip": np.fliplr,
                    "variables1d_flip": lambda x: np.flip(x)
                }[modifier])
        return(funcs)


    # ------------------------------------------------------------------------
    # strictly internal, of no use outside script

    def _findv(self, name):
        """Search template header section for variable; returns if exists."""
        
        # check if variable is in root group; if so, return; 
        inroot = name in self.structure['variables'].keys()
        if inroot:
            return(())


# ----------------------------------------------------------------------------
# Use as script
# ----------------------------------------------------------------------------

scripthelp = """
Help text goes here.
"""


def args_parser():
    """Args_handler: argument parsing for editnc.py."""

    # init argparse parser class; add 3 positional args; 1 req, 2 opt, 3 opt
    p = argparse.ArgumentParser(
        description=scripthelp,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("ncin", help="Input netCDF")
    p.add_argument("ncout", nargs="?", default=None, help="Output netCDF")
    p.add_argument("jsin", nargs="?", default=None, help="Input JSON")
    args = p.parse_args()

    # determine template mode or edit mode based on number of arguments
    ncin, ncout, jsin = args.ncin, args.ncout, args.jsin

    # check argument 1: input netCDF
    try:
        input_dataset = nc4.Dataset(ncin)
    except:
        sys.exit(print("ERROR: Invalid file passed to arg 1. Exiting."))
        print(scripthelp)

    # if argument 3 exists, check argument 2: output netCDF
    if jsin:
        # if argument 2 is a dir, make output filename from arg1
        if isdir(ncout):
            ncout = ncout+"/"+basename(splitext(ncin)[0])+"_edit.nc"
            print("INFO: Argument 2 is a directory, saving as: "+ncout)

        # try to open output
        try:
            output_dataset = nc4.Dataset(ncout, "w")
        except:
            sys.exit(print("ERROR: Failed to read arg2. Exiting."))
            print(scripthelp)

        # try to open json template
        try:
            with open(jsin, "r") as j:
                template = json.load(j)
        except:
            sys.exit(print("ERROR: Failed to read arg3. Exit."))
            print(scripthelp)

    else:
        output_dataset = None
        template = splitext(ncin)[0]+".json"

    return(input_dataset, output_dataset, template)


if __name__ == '__main__':
    
    # handle arguments, validate; return open file(s)
    input_dataset, output_dataset, template = args_parser()
    
    # if no args 2, write json template
    if output_dataset is None:
        structure = GetStructure(input_dataset)
        output_template = GetTemplate(structure)
        with open(template, "w") as j:
            json.dump(output_template, j, indent=4)

    # else, write changes to output netCDF
    else:
        # pass to job function
        editor = EditNetCDF(input_dataset, output_dataset, template)

        # close input and output netCDFs
        input_dataset.close()
        output_dataset.close()