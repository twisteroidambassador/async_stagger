from setuptools import setup, find_packages

with open('README.rst', 'rt') as readme_file:
    long_description = readme_file.read()

setup(
    name='async_stagger',
    version='0.3.1',
    description='Happy eyeballs and underlying scheduling algorithm in asyncio',
    long_description=long_description,
    long_description_content_type='text/x-rst',
    url='https://github.com/twisteroidambassador/async_stagger',
    author='twisteroid ambassador',
    author_email='twisteroid.ambassador@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Framework :: AsyncIO',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
    keywords='happy-eyeballs dual-stack tcp',
    project_urls={
        'Documentation': 'http://async_stagger.readthedocs.io',
    },
    packages=find_packages(),
    python_requires='>=3.6',
    extras_require={
        'test': ['pytest', 'pytest-asyncio', 'pytest-mock'],
    }
)
