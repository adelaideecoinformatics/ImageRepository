"""
"""

class Credentials:
    """
    Encapsulate the credentials needed to access the needed resources.
    """

    def __init__(self):
        self.authurl = "https://keystone.rc.nectar.org.au:5000/v2.0/"
        self.username = None
        self.tenant_name = None
        self.tenant_id = None
        self.password = None
        self.region_name = None


        if "OS_AUTH_URL" in os.environ:
            self.authurl = os.environ["OS_AUTH_URL"]
        if "OS_TENANT_ID" in os.environ:
            self.tenant_id = os.environ["OS_TENANT_ID"]
        if "OS_TENANT_NAME" in os.environ:
            self.tenant_name = os.environ["OS_TENANT_NAME"]
        if "OS_USERNAME" in os.environ:
            self.username = os.environ["OS_USERNAME"]
        if "OS_REGION_NAME" in os.environ:
            self.region_name = os.environ["OS_REGION_NAME"]

        if "OS_PASSWORD" in os.environ:
            self.password = os.environ["OS_PASSWORD"]

        #  Next, add some alternative ways of getting the credentials.
        #  An encrypted file sitting in a RAM disk file system would be good.

        

    def clear_password(self):
        # We may really want to work out how to ensure the original physical
        # storage can be overwritten, this will have to do for now.
        self._password = ""
        os.environ["OS_PASSWORD"] = ""
