#scrub_discover.py

from control2 import *
from scrubber import scrubPrint
import re

def scrub(ofx, siteURL, accType):
    
    if 'DISCOVERCARD' in siteURL: ofx= _scrubDiscover(ofx, accType)
    return ofx


#-----------------------------------------------------------------------------
# OFX.DISCOVERCARD.COM
#   1.  Discover OFX files will contain transaction identifiers w/ the following format:
#           FITIDYYYYMMDDamt#####, where
#                FITID  = string literal
#                YYYY   = year (numeric)
#                MM     = month (numeric)
#                DD     = day (numeric)
#                amt    = dollar amount of the transaction, including a hypen for negative entries (e.g., -24.95)
#                #####  = 5 digit serial number

#   2.  The 5-digit serial number can change each time you connect to the server, 
#          meaning that the same transaction can download with different FITID numbers.  
#       That's not good, since Money requires a unique FITID value for each valid transaction.  
#       Varying serial numbers result in duplicate transactions!

#   3.  We'll replace the 5-digit serial number with one of our own.  
#       The default will be 0 for every transaction,
#          and we'll increment by one for each subsequent transaction that that matches
#          a previous transaction in the file.

# 8/14/2016: Discover BANK now uses an FITID format of SDF######, where ###### is unique for the day.
#            The length seems to vary, but the largest observed is 6 digits  
#            Unfortunately, the digits can be assigned to multiple transactions on the same day, so it isn't 
#               guaranteed to be unique.  
#            Modified routine to uniquely handle BASTMT vs CCSTMT statements.

# NOTE:  There was brief period in late 2017 where Discover Bank changed their fitid format, but soon
#        reverted to the same as described above.

def _scrubDiscover(ofx, accType):

    global _scrub_Discover_knowns  #track of Discover FITID values between regex.sub() calls
    _scrub_Discover_knowns = []  
    
    if accType=='CCSTMT': 
        scrubPrint("Scrubber: Processing Discover Card statement.")
    else:
        scrubPrint("Scrubber: Processing Discover Bank statement.")

    ofx_final = ''      #new ofx message
    _scrub_Discover_knowns = []  #reset our global set of known vals (just in case)

    # dev: insert a line break after each transaction for readability.
    # also helps block multi-transaction matching in below regexes via ^\s option
    p = re.compile(r'(<STMTTRN>)',re.IGNORECASE)
    ofx = p.sub(r'\n<STMTTRN>', ofx)
    
    #regex p captures everything from <FITID> up to the next <tag>, but excludes the next "<".
    #p produces 2 results:  r.group(1) = <FITID> field, r.group(2)=value
    #the ^<\s prevents matching on the next < or newline
    p = re.compile(r'(<FITID>)([^<\s]+)',re.IGNORECASE)

    #call substitution (inline lamda, takes regex result = r as tuple)
    ofx_final = p.sub(lambda r: _scrubDiscover_r1(r, accType), ofx)
   
    if accType=='BASTMT':
        #regex p captures everything from <TRNTYPE>DEBIT up to the next "<" aftert the <NAME>Check tag and field.
        # Discover Bank codes checks as
        # <STMTTRN><TRNTYPE>DEBIT<...><NAME>Check ###########</STMTTRN>
        # p produces 4 results:
        #   r.group(1) = <TRNTYPE>DEBIT,
        #   r.group(2) = stuff up to next "<NAME>Check "
        #   r.group(3) = "<NAME>Check ", including the trailing spaces (at least 1)
        #   r.group(4) is the check number (1 or more digits)
        # Rearranged, the result should produce a entry that will import the check number in Money
        # <STMTTRN><TRNTYPE>CHECK<...><CHECKNUM>############<NAME>Check</STMTTRN>
        ofx = ofx_final
        p = re.compile(r'(<TRNTYPE>DEBIT)([^\s]+)(<NAME>Check[ ]+)([0-9]+)',re.IGNORECASE)
        ofx_final = p.sub(lambda r: _scrubDiscover_r2(r, accType), ofx)

    return ofx_final

def _scrubDiscover_r1(r, accType):
    #regex subsitution function: change fitid value
    global _scrub_Discover_knowns

    fieldtag = r.group(1)
    fitid = r.group(2).strip(' ')
    fitid_b = fitid                     #base fitid before annotating
    
    #strip the serial value for credit card transactions
    if accType=='CCSTMT': 
        bx = len(fitid) - 5
        fitid_b = fitid[:bx]
    
    #find a unique serial#, from 0 to 9999
    seq = 0   #default
    while seq < 9999:
        fitid = fitid_b + str(seq)
        exists = (fitid in _scrub_Discover_knowns)
        if exists:  #already used it... try another
            seq=seq+1
        else:
            break   #unique value... write it out
        
    _scrub_Discover_knowns.append(fitid)         #remember the assigned value between calls
    return fieldtag + fitid             #return the new string for regex.sub()

def _scrubDiscover_r2(r, accType):
    #regex subsitution function: insert checknum field for BANK statements
    trntype = r.group(1)
    rest = r.group(2)
    name = r.group(3).strip(' ')
    checknum = r.group(4)
    return '<TRNTYPE>CHECK' + rest + '<CHECKNUM>' + checknum + name
