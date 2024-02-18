from setuptools import setup, find_packages

setup(
    name="k8s-infer",
    version="0.0.1",
    author="dbha",
    author_email="dbha0719@gmail.com",
    description=("demonstrate python module and tool packaging."),
    # long_description=long_description,
    # long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        'argon2-cffi==23.1.0',
        'argon2-cffi-bindings==21.2.0',
        'black==23.12.1',
        'boto3==1.34.16',
        'botocore==1.34.16',
        'charset-normalizer==3.3.2',
        'click==8.1.7',
        'efficientnet-pytorch==0.7.1',
        'idna==3.6',
        'jmespath==1.0.1',
        'minio==7.2.3',
        'mypy-extensions==1.0.0',
        'numpy==1.26.3',
        'packaging==23.2',
        'pathspec==0.12.1',
        'pillow==10.2.0',
        'python-dateutil==2.8.2',
        'pycparser==2.21',
        'pycryptodome==3.20.0',
        'requests==2.31.0',
        's3transfer==0.10.0',
        'six==1.16.0',
        'tomli==2.0.1',
        'torch==1.13.1',
        'torchaudio==0.13.1',
        'torchvision==0.14.1',
        'typing_extensions==4.9.0',
        'urllib3==2.0.7'
    ],
    # packages=find_packages(include=['k8s_infer', 'k8s_infer.*']),
    packages=find_packages(),
    python_requires=">=3.6",
    entry_points={
        "console_scripts": [
            "k8s-infer = k8s_infer.cli:main"      
        ]
    }
)
