# usage: python coreDepAnalysis.py <codeFolderPath> 
# output: list of external dependencies used in the code folder, one per line
#         line format: <dependencyType> <dependencyName>
#         dependencyType: shellFile|awkFile|command
# dependencies are extracted from shell scripts and awk files in the code folder. shell scripts use source or . or 
# an import statement idiom to include other shell scripts
#        import <filename>  ;$L1;$L2  # import statement idiom. the path is determined at runtime but this tool assumes the imported file is in the same folder as the importing script
# Code Files:
#    <moduleName>.<ext>: library files have extenstions indicating their language
#    <commandName>     : commands do not have extensions but their langaguage are identified by shebang lines
#    <PlugoinName>.<PluginType> : plugins modules have extensions indicating their plugin type
# How this tool works:
#   1. identify code files in the code folder
#   2. parse each code file to create the following lists
#      a) commands/functions provided by the file
#      b) files/modules included by the file 
#      c) commands/functions used by the file
#   3. create a list of files/modules that are included but not provided in the code folder
#   4. create a list of commands/functions that are used but not provided in the code folder
#   5. classify the missing files/modules and commands/functions into dependency types
#      a) shellFile: shell scripts included but not provided in the code folder
#      b) awkFile: awk files included but not provided in the code folder
#      c) command: commands/functions used but not provided in the code folder
# Note: this tool does not handle dynamic imports or command invocations where the command name is constructed at runtime
