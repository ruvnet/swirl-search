import os
import json
from swirl.serializers import SearchProviderSerializer
from django.conf import settings
import pytest
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.core.exceptions import ObjectDoesNotExist
from swirl.processors.transform_query_processor import TransformQueryProcessorFactory, SynonymQueryProcessor
from django.contrib.auth.models import User
import re
import responses
import requests

## General and shared

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def test_suser_pw():
    return 'password'

@pytest.fixture
def test_suser(test_suser_pw):
    """
    return the user if it's aleady there, otherwise create it.
    """
    try:
        return User.objects.get(username='admin')
    except ObjectDoesNotExist:
        pass

    return User.objects.create_user(
        username='admin',
        password=test_suser_pw,
        is_staff=True,  # Set to True if your view requires a staff user
        is_superuser=True,  # Set to True if your view requires a superuser
    )

@pytest.fixture
def search_provider_pre_query_data():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Build the absolute file path for the JSON file in the 'data' subdirectory
    json_file_path = os.path.join(script_dir, 'data', 'sp_post_request.json')

    # Read the JSON file
    with open(json_file_path, 'r') as file:
        data = json.load(file)
    return data

@pytest.fixture
def mock_small_result():
    return {
    "items": [
    {
      "kind": "customsearch#result",
      "title": "Notebook | Financial Times",
      "htmlTitle": "\u003cb\u003eNotebook\u003c/b\u003e | Financial Times",
      "link": "https://www.ft.com/content/b6f32818-aeda-11da-b04a-0000779e2340",
      "displayLink": "www.ft.com",
      "snippet": "Mar 8, 2006 ... We'll send you a myFT Daily Digest email rounding up the latest MG Rover Group Ltd news every morning. Patricia Hewitt once confided to Notebook ...",
      "htmlSnippet": "Mar 8, 2006 \u003cb\u003e...\u003c/b\u003e We&#39;ll send you a myFT Daily Digest email rounding up the latest MG Rover Group Ltd news every morning. Patricia Hewitt once confided to \u003cb\u003eNotebook\u003c/b\u003e&nbsp;...",
      "formattedUrl": "https://www.ft.com/content/b6f32818-aeda-11da-b04a-0000779e2340",
      "htmlFormattedUrl": "https://www.ft.com/content/b6f32818-aeda-11da-b04a-0000779e2340",
      "pagemap": {
        "cse_thumbnail": [
          {
            "src": "https://encrypted-tbn3.gstatic.com/images?q=tbn:ANd9GcSr8n8mzhsf6uFZw3uY-3pizLTj1JFydMfMwCQ3e_GZTxjRnHSAXg5apLU",
            "width": "310",
            "height": "163"
          }
        ],
      }
    }
  ]
}

class SearchQueryTransformTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def _init_fixtures(self, api_client,test_suser, test_suser_pw, search_provider_pre_query_data, mock_small_result,):
        self._api_client = api_client
        self._test_suser = test_suser
        self._test_suser_pw = test_suser_pw
        self._search_provider_pre_query = search_provider_pre_query_data
        self._mock_small_result = mock_small_result


    def setUp(self):
        settings.SWIRL_TIMEOUT = 1
        settings.CELERY_TASK_ALWAYS_EAGER = True
        is_logged_in = self._api_client.login(username=self._test_suser.username, password=self._test_suser_pw)
        # Check if the login was successful
        assert is_logged_in, 'Client login failed'

        # Create a search provider
        #1
        serializer = SearchProviderSerializer(data=self._search_provider_pre_query)
        serializer.is_valid(raise_exception=True)
        serializer.save(owner=self._test_suser)


    def get_data(self, url):
        response = requests.get(url)
        return response.json()

    @responses.activate
    def test_request_post(self):
        # Call the viewset
        surl = reverse('search')
        # Mock the POST request
        json_response = self._mock_small_result
        url_pattern = re.compile(r'https://go\.apis\.huit\.harvard\.edu/.*')
        responses.add(responses.POST, url_pattern, json=json_response, status=200)
        response = self._api_client.get(surl, {'qs': 'pinker', 'providers':1})
        assert response.status_code == 200, 'Expected HTTP status code 200'
        resp_json = response.json()
        assert len(resp_json) == 4, 'Expected 1 transform'