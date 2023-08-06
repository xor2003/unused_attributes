from setuptools import setup

setup(
    name='unused_attributes',
    version='0.1',
    description='Find class unused attributes',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/xor2003/unused_attributes',
    author='xor2003',
    author_email='xor2003@gmx.com',
    license='GPL',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
    keywords='optimization, ununsed attributes, clean code',
    packages=['unused_attributes'],
    install_requires=[],
)
