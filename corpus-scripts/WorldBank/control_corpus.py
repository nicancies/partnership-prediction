'''Script to create control corpus for WB'''


import os
import json
import re
import shutil
import time
import traceback
import fitz
from langdetect import detect
import tqdm


file_path = os.path.dirname(os.path.abspath(__file__))
corpus_folder = f'{file_path}/../corpus'
wb_partnered_projects_folder = f'{corpus_folder}/projects/partner/WorldBank'
data_folder = f'{file_path}/data'

evaluation_documents_types = ['icr','icrr','ppar','project performance assessment report',
                              'implementation completion and results report','implementation completion report review']


def is_english_document(pdf):
    '''Check if document is english.'''
    if type(pdf) == str:
        doc = fitz.open(pdf)
    else:
        doc = fitz.open('pdf', pdf)
    all_text = ""
    english_sentences = 0
    total_sentences = 0

    contains_text = False
    for page in doc:
        if page.get_text().strip():
            contains_text = True
            text = page.get_text()
            sentences = re.split(r'(?<=[.!?]) +', text)
            for sentence in sentences:
                if sentence.strip():
                    total_sentences += 1
                    try :
                        if detect(sentence) == 'en':
                            english_sentences += 1
                    except:
                        pass
                    all_text += sentence + "\n"

    english_ratio = english_sentences / total_sentences if total_sentences > 0 else 0
    return contains_text and english_ratio > 0.5



def analyze_partnered_projects()->dict:
    '''Analyse projects that are partnered (from corpus folder). Create dict of with analysis.
    
    Dic structure:
    {
        'project_id_1': {
            'documents': [document1, document2, ...],
            'end_date' : <year>,
        },
        'project_id_2': {
            'documents': [document1, document2, ...],
            'end_date' : <year>,
        },
        ...
    }
    '''


    analyzes = {}

    if os.path.isdir(wb_partnered_projects_folder):

        for project in os.listdir(wb_partnered_projects_folder):
            if os.path.isdir(f'{wb_partnered_projects_folder}/{project}'):

                # read metadata
                metadata = json.load(open(f'{wb_partnered_projects_folder}/{project}/metadata.json'))
                country = metadata['countrycode'][0]
                end_year = metadata['end_date']

                analyzes[project] = {
                    'documents': [], ## TODO: change to list if needed
                    'end_date' : end_year,
                    'country' : country,
                    'sector_code' : metadata['sectorcode'] if 'sectorcode' in metadata else None,
                }

                # read documents
                for document in os.listdir(f'{wb_partnered_projects_folder}/{project}'):
                    if document.endswith('.pdf'):
                        analyzes[project]['documents'].append(document)


    return analyzes



def get_control_project(counterpart_project:dict, possible_projects:dict=None)->str:
    '''Get control project for WB. It needs to be a project that is not partnered, has at least one evaluation document, and should have closed in the same year as the counterpart project.'''
    control_project = None
    

    priority_evaluation_doc = True
    priority_end_year = True if counterpart_project['end_date'] else False
    priority_sector = True if counterpart_project['sector_code'] else False
    priority_country = True
    possible_projects_keys = list(possible_projects.keys())
    i = 0
    while i < len(possible_projects) and not control_project:
        valid = True
        project_id = possible_projects_keys[i]
        project = possible_projects[project_id]
        project_country = project['country']
        projects_folder = f'{data_folder}/{project_country}'
        project_docs = os.listdir(f'{projects_folder}/{project_id}')
        metadata = project['metadata']

        ## check if project has same country
        if priority_country:
            if project['country'] != counterpart_project['country']:
                valid = False


        ## check if project has same end year
        if priority_end_year and valid:
            project_duration = metadata['end_date']
            if not project_duration or project_duration != counterpart_project['end_date']:
                valid = False


        ## check if at least one sector in common
        if priority_sector and valid:
            project_sectors = metadata['sectorcode'] if 'sectorcode' in metadata else []
            common_sectors = [s for s in project_sectors if s in counterpart_project['sector_code']]
            if not common_sectors:
                valid = False

        # check priorities
        ## check if project has evaluation document
        if priority_evaluation_doc and valid:
            has_evaluation_doc = False
            for doc in project_docs:
                for evaluation_doc in evaluation_documents_types:
                    if evaluation_doc in doc.lower():
                        has_evaluation_doc = True
                        break
                if has_evaluation_doc:
                    break
            if not has_evaluation_doc:
                valid = False

        if valid:
            control_project = f'{projects_folder}/{project_id}'


        if control_project:
            valid_doc = False
            # check if at least one evaluation document is in english and not broken
            for doc in project_docs:
                for evaluation_doc in evaluation_documents_types:
                    if evaluation_doc in doc.lower():
                        try:
                            # check if can open pdf
                            pdf = fitz.open( f'{projects_folder}/{project_id}/{doc}')
                            # check if doc is english
                            if is_english_document(f'{projects_folder}/{project_id}/{doc}'):
                                valid_doc = True
                                break
                        except Exception as e:
                            print(traceback.format_exc())

            if not valid_doc:
                control_project = None
                # remove project from list
                possible_projects.pop(project_id)
                possible_projects_keys = list(possible_projects.keys())
                i -= 1
        

        i += 1
        # if none found, remove priority and check again
        if i == len(possible_projects) and not control_project:
            i = 0
            if priority_end_year:
                priority_end_year = False
            elif priority_sector:
                priority_sector = False
            elif priority_country:
                priority_country = False
                # reset other priorities
                priority_end_year = True
                priority_sector = True
            else:
                break


    return control_project

def create_control_corpus(analyzes: dict):
    '''Create control corpus for WB'''

    control_corpus_path = f'{file_path}/control_corpus'

    # create control corpus folder
    if not os.path.exists(control_corpus_path):
        os.makedirs(control_corpus_path)

    matched_projects = 0
    available_projects = {}
    for country in os.listdir(data_folder):
        for project in os.listdir(f'{data_folder}/{country}'):
            # check if not partnered
            metadata = json.load(open(f'{data_folder}/{country}/{project}/metadata.json'))
            if 'partnerships' in metadata and metadata['partnerships']:
                continue

            available_projects[project] = {
                'country' : country,
                'metadata' : metadata
            }

    print('Number of available projects:', len(available_projects))

    p_bar = tqdm.tqdm(total=len(analyzes))

    for project in analyzes:
        
        p_bar.update(1)

        # find control project
        control_project_path = get_control_project(analyzes[project],available_projects)

        if control_project_path:
            control_project_id = control_project_path.split('/')[-1]
            control_project_country = available_projects[control_project_id]['country']

            # create country folder
            if not os.path.exists(f'{control_corpus_path}/{control_project_country}'):
                os.makedirs(f'{control_corpus_path}/{control_project_country}')


            # add control project to corpus
            if not os.path.exists(f'{control_corpus_path}/{control_project_country}/{control_project_id}'):
                os.makedirs(f'{control_corpus_path}/{control_project_country}/{control_project_id}')

            # copy metadata
            shutil.copy(f'{control_project_path}/metadata.json', f'{control_corpus_path}/{control_project_country}/{control_project_id}/metadata.json')

            # copy evaluation docs to control corpus
            for document in os.listdir(control_project_path):
                for evaluation_doc in evaluation_documents_types:
                    try:
                        if evaluation_doc in document.lower() and is_english_document(f'{control_project_path}/{document}'):
                            shutil.copy(f'{control_project_path}/{document}', f'{control_corpus_path}/{control_project_country}/{control_project_id}/{document}')
                            break
                    except:
                        pass
            del available_projects[control_project_id]
                        
            matched_projects += 1
        else:
            print(f'No control project found for {project}')

    print(f'Number of matched projects: {matched_projects}')

            

            




if __name__ == "__main__":
    
    analyzes = analyze_partnered_projects()
    print(analyzes)
    print('Number of partnered projects:', len(analyzes))

    create_control_corpus(analyzes)