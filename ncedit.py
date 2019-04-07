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
import datetime as dt
import netCDF4 as nc4
from calendar import monthrange
from collections import OrderedDict
from os.path import join, isfile, isdir, basename, splitext

# ----------------------------------------------------------------------------
# Handle time
# ----------------------------------------------------------------------------

# regular expressions for validating input CF units for time
timeunitsre = re.compile(
    ".* since [0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1])"
    ".*(2[0-3]|[01][0-9]):[0-5][0-9]:[0-5][0-9].*")
    

def month_bnds(x):
    """Return tuple of month_bnds for input datetime."""
    return((x.replace(day=1), x.replace(day=monthrange(x.year, x.month)[1])))


def day_bnds(x, length, offset=0.5):
    """Return tuple of day_bnds for input datetime."""
    off = dt.timedelta(days=length*offset)
    return((x-off, x+off))

# Functions for generating time bounds from input numpy arrays
GetTimeBnds = {
    "months": np.vectorize(month_bnds),
    "days": np.vectorize(day_bnds)}


def ConvertTime(netcdf_object, time_options):
    """Time validation and translation (assumes CF compliance)."""

    if not all([time_options["in_units"], time_options["out_units"]]):
        print("INFO: No time conversion specified. Skipping.")
        return(None)

    elif not all([
        timeunitsre.fullmatch(time_options['in_units']), 
        timeunitsre.fullmatch(time_options['out_units'])]):
        print("INFO: Input time units not CF compliant; no conversion.")
        return(None)

    else:
        try:
            in_time = netcdf_object.variables["time"]
        except:
            print("INFO: Time not found in input netCDF; no conversion.")
            return(None)

    # add other calendar options to code later
    in_units = time_options['in_units']
    in_origin = in_units.split("since")[1].strip()[:19]
    in_datetime = dt.datetime.strptime(in_origin, "%Y-%m-%d %H:%M:%S")
    in_time_dt = nc4.num2date(in_time[:], in_units, calendar="standard")
    
    out_units = time_options['out_units']
    #out_common_units = out_units.split("since")[0]
    out_origin = out_units.split("since")[1].strip()[:19]
    out_datetime = dt.datetime.strptime(out_origin, "%Y-%m-%d %H:%M:%S")

    time_shift = in_datetime-out_datetime
    out_time_dt = in_time_dt-time_shift

    bnds = time_options["set_time_bnds"]
    if bnds:
        lo, hi = GetTimeBnds[bnds](out_time_dt)
        lo = [nc4.date2num(t, out_units) for t in lo]
        hi = [nc4.date2num(t, out_units) for t in hi]
        out_time_bnds = [t for t in zip(lo, hi)]
    else:
        out_time_bnds = None

    out_time = nc4.date2num(out_time_dt, out_units)
    return(out_time, out_time_bnds)


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


# ----------------------------------------------------------------------------
# Some random stuff
# ----------------------------------------------------------------------------


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
                ("in_units", GetTimeUnits(s)), 
                ("out_units", None), 
                ("set_time_bnds", None)])),
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


def GetModifiers(name, permute):
    return([{
        "variables2d_yflip": np.flipud,
        "variables2d_xflip": np.fliplr,
        "variables1d_flip": lambda x: np.flip(x)
    }[mod] for mod, vars in permute.items() if name in vars])


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
        self.UpdateTime()
        #self.UpdateMisc()


    def UpdateTime(self):
        """Time validation and translation (assumes CF compliance)."""

        # time translation/conversion
        out_time, out_time_bnds = ConvertTime(self.ncin, self.time)
        out_units = self.time["out_units"]

        self.ncout.variables["time"][:] = out_time
        self.ncout.variables["time"].units = out_units
        if out_time_bnds:
            try:
                self.ncout.variables["time_bnds"][:] = out_time_bnds
                self.ncout.variables["time_bnds"].units = out_units
            except:
                #self.ncout.createDimension("nv", 2)
                self.WriteVariable(
                    "time_bnds", ("time","nv"), {"units": out_units}, 
                    dtype="f4", data=out_time_bnds)


    def UpdateArray(self, name, variable, fill=None):
        """Edit input array."""

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
        npfuncs = GetModifiers(name, self.permute)#npfuncs=self.GetModifiers(name)
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
        """Copy/edit variable to output netCDF."""

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
        """Copy/edit grouped variables to output netCDF."""

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
            
            # get new name (or old name, whatever); add prefix if group
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
    
    # handle arguments, validate; return open file(s) # C:\Users\jjmcn\git\netCDFeditor\ncedit.py
    input_dataset, output_dataset, template = args_parser()

    # if no args 2, write json template
    if output_dataset is None:
        output_template = GetTemplate(input_dataset)
        with open(template, "w") as j:
            json.dump(output_template, j, indent=4)

    # else, write changes to output netCDF
    else:
        # pass to job function
        editor = EditNetCDF(input_dataset, output_dataset, template)

        # close input and output netCDFs
        input_dataset.close()
        output_dataset.close()