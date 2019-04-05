# netCDFeditor
A python script that generates netCDF structure templates in json format and writes new netCDF files. The internals are designed to be as flexible as possible. You will for sure find ways to break the tool, particularly when passing in custom functions to apply to the variable arrays, but rest assured that you can't harm the input copy of the files. Some key points:

* inputs are opened in read-only mode, always; wildcards should work, but haven't been thoroughly tested
* output filenames have *_edit.nc* appended unless a name is provided at argument position two
* arguments one and two are always required, a file or a directory:
    * two arguments: writes json template(s) generated for input netCDF(s) (arg1) to output file or directory (arg2)
    * three arguments: copies data from input netCDF(s) (arg1) to output netCDF(s) in output directory (arg2) while applying changes indicated using the JSON template (arg3; only one template allowed)


## usage

The script should be used in three steps:

1. **Generate templates for input netCDF(s).**
```{shell}
$ [python3] ncedit.py <input_netCDF_or_directory> <output_netCDF_or_directory>
```
If a directory is given for argument one, a directory must be given for argument two; but, a file may be given for argument one and a directory for argument two.       

2. **Edit the template(s) to reflect the desired changes to apply when generating output netCDF(s).**       
See the section below for better explanation of how the template is applied to outputs. Only one template can be given each time you run the script in *edit* mode.     
  
Changes are applied in a flexible way. Variables in input netCDF(s) that aren't listed in the provided template are simply copied without any changes. Variables in the provided template that don't exist in the input netCDF(s) have no affect on the output(s). For these reasons, you can paste all of the necessary updates for multiple sets of disparate netCDF files into a single template and update all at once unless they share common variable names with incompatible attributes; e.g. two sets of files with different origins for variable *time* cannot be edited with the same template.

3. **Copy data from input netCDF(s) to output netCDF(s), applying changes specified in the input JSON template.**
```{shell}
$ [python3] ncedit.py <input_netCDF_or_directory> <output_netCDF_or_directory> <input_template>.json
```

## format of <template>.json
### `header`
This section under the `header` element of the JSON is primarily for manipulating file structure/metadata associated with the variables. Changes to the attribute names and values in this section will be reflected in the output file. Also, add/remove dimensions associated with a variable; e.g. in the netCDF to which the template below is applied, the variable *lat* will have the value "THE WRONG standard_name" for the *standard_name* attribute.

```{json}
{
    "header": {
        "variables": {
            "lat": {
                "attributes": {
                    "standard_name": "THE WRONG standard_name",
                    "units": "degrees_north",
                    "long_name": "latitude coordinate"
                },
                "dimensions": [
                    "y",
                    "x"
                ]
            } ...,
		},
		"dimensions": { ... },
		"attributes": { ... } 
```

### `updates`
The `updates` section is for changes to the output that can't be specified in the header element for one reason or another. For example, dims, groups, variables can't be renamed using the header because the names are used to index the variables in the source netCDF during the copy to the destination netCDF. 

#### `rename`
The section under `rename` maps the original dimension, group, variable names (key) to the desired names (value) in the output file. For example, for file to which the template below is applied, the input variable *prcp* will be renamed to *PRECIPITATION* in the output file.

```{json}
    "updates": {
        "rename": {
            "variables": {
                "prcp": "PRECIPITATION",   
                "time_bnds": "time_bnds",
                "lat": "lat", ...
            },
            "dimensions": {
                "x": "x",
                "y": "y",
                "nv": "nv",
                "time": "time"
            }
        }, ...
```

#### `permute`
The `permute` section applies some basic numpy transformations to the arrays for variables in each of the lists. Fore example, variable names listed under `list_variables_invert_y` will have their arrays flipped along the y axis. More to come.

```{json}
         "permute": {
            "list_variables_invert_y": [],
            "list_variables_invert_x": []
        }, ...
```

#### `applyfuncx`
The `applyfuncx` section allows the user to apply basic arithmetic operations to the variable arrays. This set of options undoubtedly is the biggest source of potential bugs. The idea is that the user can supply any number of basic arithmetic operations as a function of x, where x is the variable array, and those will be applied in that order. Python will attempt to evaluate the input strings as functions to apply to array *x*, and will simply print a failure message to stdout if the input string is incompatible for whatever reason. 

For example, for file to which the template below is applied, the input variable *prcp* will be:
* multiplied by 10, then
* summed with 4, then
* squared

```{json}
        "applyfuncx": {
            "prcp": ["x*10", "x+4", "x*x"],
            "time_bnds": [], ...
        }, ...
```

FYI, these operators have been tested:

```{python}
>>> import numpy as np
>>> x = np.array([0,1,2,3,4,5,6,7,8,9])

# addition
>>> x+10
array([10, 11, 12, 13, 14, 15, 16, 17, 18, 19])

# subtraction
>>> x-10
array([-10,  -9,  -8,  -7,  -6,  -5,  -4,  -3,  -2,  -1])

# multiplication
>>> x*10
array([ 0, 10, 20, 30, 40, 50, 60, 70, 80, 90])

# division
>>> x/10
array([0. , 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])

# remainder
>>> x%10
array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], dtype=int32)

# exponentiation
>>> x**10
array([         0,          1,       1024,      59049,    1048576,
          9765625,   60466176,  282475249, 1073741824, -808182895], dtype=int32)

# floor division
>>> x//10
array([0, 0, 0, 0, 0, 0, 0, 0, 0, 0], dtype=int32)
```

#### `other`
The remaining update options listed below should be self-explanatory.

```{json}
        "compression_level": 4   # RANGE 1-9
```