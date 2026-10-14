from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

version = "0.0.1"

setup(
    name="isoft_business_ai",
    version=version,
    description="Conversational business intelligence for ERPNext, backed by verified query tools",
    author="ISOFT",
    author_email="ai.accounts@isoft.co.ao",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
