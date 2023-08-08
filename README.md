# Unused attributes

This utility helps to identify attributes in Python objects that have been assigned a value but are never accessed or read in the code. 
These attributes are likely unused variables that can be removed, resulting in cleaner code and slightly improved performance.

To use this utility, provide your main script file as the first argument:

    unused_attributes.py <tartget_script.py>

During runtime, it is recommended to thoroughly test your program, ensuring that all parts of the code are executed. 

Upon program exit, the utility will print the results indicating the usage status of the attributes.

For example:

    unused_attributes ./test.py

    Collection started
    2
    /home/xor/unused_attributes/test.py:6:1: W001: in class C variable b was never read
    /home/xor/unused_attributes/test.py:6:1: W001: in class C variable e was never read

