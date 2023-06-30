'''
@author:     Sid Probstein
@contact:    sid@swirl.today
'''

from datetime import datetime

from jsonpath_ng import parse
from jsonpath_ng.exceptions import JsonPathParserError

from django.conf import settings

from swirl.processors.processor import *
from swirl.processors.utils import get_tag, clean_string, create_result_dictionary, get_mappings_dict

#############################################
#############################################

class GenericQueryProcessor(QueryProcessor):

    type = 'GenericQueryProcessor'

    def process(self):
        return clean_string(self.query_string).strip()

#############################################

class TestQueryProcessor(QueryProcessor):

    type = 'TestQueryProcessor'

    def process(self):
        return clean_string(self.query_string).strip() + " test"

#############################################

class GenericResultProcessor(ResultProcessor):

    type="GenericResultProcessor"

    def process(self):

        use_payload = True
        file_system = False
        result_block = None
        if 'NO_PAYLOAD' in self.provider.result_mappings:
            self.warning(f"NO_PAYLOAD is not supported by GenericResultProcessor, ignoring")
        if 'FILE_SYSTEM' in self.provider.result_mappings:
            file_system = True
        if 'BLOCK' in self.provider.result_mappings:
            result_block = get_mappings_dict(self.provider.result_mappings)['BLOCK']

        list_results = []
        result_number = 1

        for result in self.results:
            swirl_result = create_result_dictionary()
            # payload = {}
            # report searchprovider rank, not ours
            swirl_result['searchprovider_rank'] = result_number
            swirl_result['date_retrieved'] = str(datetime.now())

            #############################################
            # copy fields, avoiding collisions
            for key in result.keys():
                if key in swirl_result.keys():
                    if not swirl_result[key]:
                        swirl_result[key] = result[key]
             # end for

            if swirl_result['date_published'] == "":
                swirl_result['date_published'] = 'unknown'

            #############################################
            # final assembly
            swirl_result['payload'] = {}

            # mark results from SearchProviders with result_mapping FILE_SYSTEM
            if file_system:
                swirl_result['_relevancy_model'] = 'FILE_SYSTEM' 

            if result_block:
                swirl_result['result_block'] = result_block

            # try to find a title, if none provided
            if swirl_result['title'] == "":
                if swirl_result['url']:
                    swirl_result['title'] = swirl_result['url']
                elif swirl_result['author']:
                    swirl_result['title'] = swirl_result['author']
                # end if
            # end if
            swirl_result['searchprovider'] = self.provider.name
            list_results.append(swirl_result)
            result_number = result_number + 1
            if result_number > self.provider.results_per_query:
                # self.warning("Truncating extra results, found & retrieved may be incorrect")
                break
        # end for

        self.processed_results = list_results
        self.modified = len(self.processed_results)
        return self.modified

#############################################

SWIRL_MAX_FIELD_LEN = getattr(settings, 'SWIRL_MAX_FIELD_LEN', 256)
FIELDS_TO_LIMIT = ['title', 'body']

class LenLimitingResultProcessor(ResultProcessor):

    type="LenLimitingResultProcessor"

    def process(self):

        # identify the requested temporal distance 
        
        max_length = get_tag('max_length', self.tags)                    
        if max_length:
            if type(max_length) != int:
                if type(max_length) == str:
                    max_length=int(max_length)
                else:
                    self.error(f"Can't extract max_length from tag: {max_length}")
                    return 0
        else:
            max_length = SWIRL_MAX_FIELD_LEN

        self.warning(f"tags: {self.tags}, max_length: {max_length}")

        modified = 0
        for item in self.results:
            for field in FIELDS_TO_LIMIT:
                if field in item:
                    if type(item[field]) == str:
                        if len(item[field]) > max_length:
                            item['payload'][field+'_full'] = item[field]
                            item[field] = item[field][:max_length-3] + '...'
                            modified = modified + 1

        self.processed_results = self.results
        self.modified = modified
        return self.modified

#############################################

class TestResultProcessor(ResultProcessor):

    type="TestResultProcessor"

    def process(self):

        # to do: test to ensure operation on a SWIRL result, i.e. after Generic or MappingResultProcessor
        for item in self.results:
            item['test'] = True

        self.processed_results = self.results
        self.modified = len(self.processed_results)
        return self.modified

#############################################

class DuplicateHalfResultProcessor(ResultProcessor):

    type="DuplicateHalfResultProcessor"

    def process(self):

        # to do: test to ensure operation on a SWIRL result, i.e. after Generic or MappingResultProcessor
        switch = 0
        results_hd = []
        for item in self.results:
            if switch == 0:
                results_hd.append(item)
                switch = 1
                continue
            if switch == 1:
                switch = 0
                continue
        # end for

        self.processed_results = self.results + results_hd
        self.modified = len(self.processed_results)
        return self.modified
