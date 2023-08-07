'''
Created on Jul 29, 2014

@author: matt
'''
import re
import sys

if __name__ == '__main__':
    
    if len(sys.argv) > 1:
        input_filename = sys.argv[1]
        output_filename = 'o_' + input_filename
    
        qif_input_file = open(input_filename, 'r')
        qif_output_file = open(output_filename, 'w')
    
        input_str = qif_input_file.read()
        uk_date_pattern = re.compile(r'D(\d{2})/(\d{2})')
        output_str = re.sub(uk_date_pattern, r'D\2/\1', input_str)
       
        qif_output_file.write(output_str)
        
        qif_input_file.close()
        qif_output_file.close()
        
    else:
        print ('UkToUsDate: Expected 1 parameter as filename\n')
        print ('UkToUsDate: Usage - python UkToUsDate.py <filename>')
