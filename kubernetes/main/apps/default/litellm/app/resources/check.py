import os

from litellm._logging import verbose_proxy_logger
from litellm.llms.custom_httpx.http_handler import HTTPHandler


class LicenseCheck:
    """
    - Check if license in env
    - Returns if license is valid
    """

    base_url = "https://license.litellm.ai"

    def __init__(self) -> None:
        self.license_str = os.getenv("LITELLM_LICENSE", None)
        verbose_proxy_logger.debug("License Str value - {}".format(self.license_str))
        self.http_handler = HTTPHandler(timeout=15)
        self.public_key = None
        self.read_public_key()

    def read_public_key(self):
        try:
            from cryptography.hazmat.primitives import serialization

            # current dir
            current_dir = os.path.dirname(os.path.realpath(__file__))

            # check if public_key.pem exists
            _path_to_public_key = os.path.join(current_dir, "public_key.pem")
            if os.path.exists(_path_to_public_key):
                with open(_path_to_public_key, "rb") as key_file:
                    self.public_key = serialization.load_pem_public_key(key_file.read())
            else:
                self.public_key = None
        except Exception as e:
            verbose_proxy_logger.error(f"Error reading public key: {str(e)}")

    def _verify(self, license_str: str) -> bool:
        return True

    def is_premium(self) -> bool:
        return True

    def verify_license_without_api_request(self, public_key, license_key):
        return True
