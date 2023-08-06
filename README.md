# Unused attributes

This utility identifies attributes in Python objects that have been assigned a value but are never accessed or read.

To use this utility, simply copy the file named "unused_attrs.py" into your project directory. Then, in your main file, add the following import statement:

    from src.unused_attrs import tracer

During runtime, it is recommended to thoroughly test your program, ensuring that all parts of the code are executed. 

Upon program exit, the utility will print the results indicating the usage status of the attributes.