'''
@author:     Sid Probstein
@contact:    sid@swirl.today
@version:    SWIRL 1.3
'''

from sys import path
from os import environ
import time

import django
from django.db import Error
from django.core.exceptions import ObjectDoesNotExist

from swirl.utils import swirl_setdir
path.append(swirl_setdir()) # path to settings.py file
environ.setdefault('DJANGO_SETTINGS_MODULE', 'swirl_server.settings') 
django.setup()

from django.conf import settings

from celery.utils.log import get_task_logger
logger = get_task_logger(__name__)

from swirl.models import Search, Result, SearchProvider
from swirl.connectors.utils import get_mappings_dict
from swirl.processors import *

SWIRL_OBJECT_LIST = SearchProvider.QUERY_PROCESSOR_CHOICES + SearchProvider.RESULT_PROCESSOR_CHOICES + Search.PRE_QUERY_PROCESSOR_CHOICES + Search.POST_RESULT_PROCESSOR_CHOICES

SWIRL_OBJECT_DICT = {}
for t in SWIRL_OBJECT_LIST:
    SWIRL_OBJECT_DICT[t[0]]=eval(t[0])

########################################
########################################

class Connector:

    type = "SWIRL Connector"

    ########################################

    def __init__(self, provider_id, search_id, update):

        self.provider_id = provider_id
        self.search_id = search_id
        self.update = update
        self.status = 'INIT'
        self.provider = None
        self.search = None
        self.query_string_to_provider = ""
        self.query_to_provider = ""
        self.query_mappings = {}
        self.response_mappings = {}
        self.result_mappings = {}
        self.response = None
        self.found = -1
        self.retrieved = -1
        self.results = []
        self.processed_results = []
        self.messages = []
        self.start_time = None

        # get the provider and query
        try:
            self.provider = SearchProvider.objects.get(id=self.provider_id)
            self.search = Search.objects.get(id=self.search_id)
        except ObjectDoesNotExist as err:
            self.error(f'ObjectDoesNotExist: {err}')
            return

        self.query_mappings = get_mappings_dict(self.provider.query_mappings)
        self.response_mappings = get_mappings_dict(self.provider.response_mappings)
        self.result_mappings = get_mappings_dict(self.provider.result_mappings)

        self.status = 'READY'

    ########################################

    def __str__(self):
        return f"{self.type}_{self.search_id}_{self.provider_id}"

    ########################################

    def message(self, message):
        self.messages.append(f'[{datetime.now()}] {message}')

    def error(self, message, save_results=True):
        logger.error(f'{self}: {message}')
        self.message(f'Error: {message}')
        self.status = 'ERROR'
        if save_results:
            self.save_results()

    def warning(self, message):
        logger.warning(f'{self}: {message}')

    ########################################

    def federate(self):

        '''
        Executes the workflow for a given search and provider
        ''' 
        
        self.start_time = time.time()

        if self.status == 'READY':
            self.status = 'FEDERATING'
            try:
                self.process_query()
                self.construct_query()
                v = self.validate_query()
                if v:
                    self.execute_search()
                    if self.status not in ['FEDERATING', 'READY']:
                        self.error(f"execute_search() failed, status {self.status}")
                    if self.status == 'FEDERATING':
                        self.normalize_response()
                    if self.status not in ['FEDERATING', 'READY']:
                        self.error(f"normalize_response() failed, status {self.status}")
                    else:
                        self.process_results()
                    if self.status == 'READY':
                        res = self.save_results()
                        if res:
                            return True
                        else:
                            return False
                    else:
                        self.error(f"process_results() failed, status {self.status}")
                        return False
                else:
                    self.error(f'validate_query() failed: {v}')
                    return False
                # end if
            except Exception as err:
                self.error(f'{err}')
                return False
            # end try
        else:
            self.error(f'unexpected status: {self.status}')
            return False
        # end if

    ########################################

    def process_query(self):

        '''
        Invoke the specified query_processor for this provider on search.query_string_processed, store the result in self.query_string_to_provider
        ''' 

        logger.info(f"{self}: process_query()")
        processor_list = []
        if self.provider.query_processor:
            processor_list = [self.provider.query_processor]
            if self.provider.query_processors:
                self.warning("Ignoring searchprovider.query_processors, since searchprovider.query_processor is specified")
        else:
            processor_list = self.provider.query_processors

        for processor in processor_list:
            logger.info(f"{self}: invoking processor: {processor}")
            try:
                processed_query = eval(processor, {"processor": processor, "__builtins__": None}, SWIRL_OBJECT_DICT)(self.search.query_string_processed, self.provider.query_mappings, self.provider.tags).process()
            except (NameError, TypeError, ValueError) as err:
                self.error(f'{processor}: {err.args}, {err}')
                return
            if processed_query:
                if processed_query != self.search.query_string_processed:
                    self.message(f"{processor} rewrote {self.provider.name}'s query to: {processed_query}")
                self.query_string_to_provider = processed_query
            else:
                self.query_string_to_provider = self.search.query_string_processed
            # end if
        # end for
        return

    ########################################

    def construct_query(self):

        '''
        Turn the query_string_processed into the query_to_provider
        ''' 

        logger.info(f"{self}: construct_query()")
        self.query_to_provider = self.query_string_to_provider
        return

    ########################################

    def validate_query(self):
       
        '''
        Validate the query_to_provider, and return True or False
        ''' 

        logger.info(f"{self}: validate_query()")
        if self.query_to_provider == "":
            self.error("query_to_provider is blank or missing")
            return False
        return True

    ########################################

    def execute_search(self):
    
        '''
        Connect to, query and save the response from this provider 
        ''' 

        logger.info(f"{self}: execute_search()")
        self.found = 1
        self.retrieved = 1
        self.response = [ 
            {
                'title': f'{self.query_string_to_provider}', 
                'body': f'Did you search for {self.query_string_to_provider}?', 
                'author': f'{self}'
            }
        ]
        self.message(f"Connector.execute_search() created 1 mock response")
        return

    ########################################

    def normalize_response(self):
        
        '''
        Transform the response from the provider into a json (list) and store as results
        ''' 

        logger.info(f"{self}: normalize_response()")
        if self.response:
            if len(self.response) == 0:
                # no results, not an error
                self.retrieved = 0
                self.message(f"Retrieved 0 of 0 results from: {self.provider.name}")
                self.status = 'READY'
                return

        # to do: review the below it may be dangerous
        self.results = self.response
        return

    ########################################

    def process_results(self):

        '''
        Process the json results through the specified result processor for the provider, updating processed_results
        ''' 

        logger.info(f"{self}: process_results()")
        if self.found > 0:
            # process results
            if self.results:
                retrieved = len(self.results)
            if not self.update:
                self.message(f"Retrieved {retrieved} of {self.found} results from: {self.provider.name}")
            processor_list = []
            if self.provider.result_processor:
                processor_list = [self.provider.result_processor]
                if self.provider.result_processors:
                    self.warning("Ignoring result_processors, since result_processor is specified")
            else:
                processor_list = self.provider.result_processors

            processor_input = self.results
            processor_output = None

            for processor in processor_list:
                
                logger.info(f"{self}: invoking processor: {processor}")
                try:
                    processor_output = eval(processor, {"processor": processor, "__builtins__": None}, SWIRL_OBJECT_DICT)(processor_input, self.provider, self.query_string_to_provider).process()
                except (NameError, TypeError, ValueError) as err:
                    self.error(f'{processor}: {err.args}, {err}')
                    return

                if processor_output:
                    processor_input = processor_output
                else:
                    # to do: document
                    self.search.status = "ERR_RESULT_PROCESSING"
                    self.error(f"{processor} returned no results")
                    return

            self.processed_results = processor_output
            if self.processed_results:
                self.status = 'READY'

        # end if
        return

    ########################################

    def save_results(self):

        '''
        Store the transformed results as a Result object in the database, linked to the search_id
        ''' 

        logger.info(f"{self}: save_results()")
        # timing
        end_time = time.time()

        # gather processor lists
        query_processors = []
        if self.search.pre_query_processor:
            query_processors.append(self.search.pre_query_processor)
        else:
            query_processors = query_processors + self.search.pre_query_processors
        # end if
        if self.provider.query_processor:
            query_processors.append(self.provider.query_processor)
        else:
            query_processors = query_processors + self.provider.query_processors
        # end if
        result_processors = []
        if self.provider.result_processor:
            result_processors = [self.provider.result_processor]
        else:
            result_processors = self.provider.result_processors
        # end if

        if self.update:
            try:
                result = Result.objects.filter(search_id=self.search, provider_id=self.provider.id)
            except ObjectDoesNotExist as err:
                self.search.status = "ERR_RESULT_NOT_FOUND"
                self.error(f'Update failed: results not found: {err}', save_results=False)
                return False
            if len(result) != 1:
                # to do: document
                self.search.status = "ERR_DUPLICATE_RESULT_OBJECTS"
                self.error(f"Update failed: found {len(result)} result objects, expected 1", save_results=False)
                return False
            # load the single result object now :\
            result = Result.objects.get(id=result[0].id)
            # add new flag       
            for r in self.processed_results:
                r['new'] = True
            try:
                result.messages = result.messages + self.messages
                result.found = max(result.found, self.found)
                result.retrieved = result.retrieved + self.retrieved
                result.time = f'{result.time + (end_time - self.start_time):.1f}'
                result.json_results = result.json_results + self.processed_results
                result.query_processors = query_processors
                result.result_processors = result_processors
                result.status = 'UPDATED'
                logger.info(f"{self}: Result.save()")
                result.save()
            except Error as err:                 
                self.error(f'save_results() update failed: {err.args}, {err}', save_results=False)
                return False
            logger.info(f"{self}: Update: added {len(self.processed_results)} new items to result {result.id}")
            self.message(f"Retrieved {len(self.processed_results)} new results from: {result.searchprovider}")
            return True
        # end if

        try:
            logger.info(f"{self}: Result.create()")
            new_result = Result.objects.create(search_id=self.search, searchprovider=self.provider.name, provider_id=self.provider.id, query_string_to_provider=self.query_string_to_provider, query_to_provider=self.query_to_provider, query_processors=query_processors, result_processors=result_processors, messages=self.messages, status='READY', found=self.found, retrieved=self.retrieved, time=f'{(end_time - self.start_time):.1f}', json_results=self.processed_results, owner=self.search.owner)
            new_result.save()
        except Error as err:
            self.error(f'save_results() failed: {err.args}, {err}', save_results=False)
        return True