# netCDFeditor
A python script that generates netCDF structure templates in json format and writes new netCDF files.

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

#### `other`
The remaining update options listed below should be self-explanatory.

```{json}
        "compression_level": 4   # RANGE 1-9
```