# 2021-09-15*rlc: this scrub routine has been deprecated and is not accurate or needed
#                 kept temporarily as a placeholder to overwrite existing copies during updates

'''
scrub_troweprice.py
from control2 import *
from scrubber import scrubPrint
import re
'''

def scrub(ofx, siteURL, accType):
    #if 'TROWEPRICE.COM' in siteURL: ofx = _scrubTRowePrice(ofx)
    return ofx

'''
def _scrubTRowePrice(ofx):
    global stat
    ofx_final = ''      #new ofx message
    stat = False
    if Debug: scrubPrint('Function _scrubTRowePrice(OFX) called')

    #Process all <REINVEST>...</REINVEST> transactions
    #Use non-greedy quantifier .+? to avoid matching across transactions.
    p = re.compile(r'<REINVEST>.+?</REINVEST>',re.IGNORECASE)
    #re.sub() command operates on every non-overlapping occurence of pattern when passed a function for replacement
    ofx_final = p.sub(lambda r: _scrubTRowePrice_r1(r), ofx)

    if stat: scrubPrint("Scrubber: T Rowe Price dividends/capital gains paid out.")

    return ofx_final

def _scrubTRowePrice_r1(r):
    #regex subsitution function: if <UNITS>0.0 then convert transaction from <REINVEST> to <INCOME>

    global stat
    
    #Copy the reinvested transaction for manipulation
    ReinvTrans = r.group(0)
    #Create variable for the paid out transaction
    PaidTrans = ''

    # If units are 0.0 then scrub the ofx transaction
    if '<UNITS>0.0<' in ReinvTrans.upper():
        #Flag that at least one transaction is scrubbed
        stat = True

        #Use regex to parse the REINVEST transaction with following format
        #<REINVEST>...<MEMO>erroneous memo</INVTRAN>...<INCOMETYPE>DIV or CGSHORT or CGLONG<TOTAL>-#.##<SUBACCTSEC>CASH<UNITS>0.0<UNITPRICE>33.33</REINVEST>
        #into these 10 groups:
        #   m.group(1) = <REINVEST>
        #   m.group(2) = ...<MEMO>
        #   m.group(3) = erroneous memo
        #   m.group(4) = </INVTRAN>...<INCOMETYPE>
        #   m.group(5) = type of income (eg DIV, CGSHORT, CGLONG)
        #   m.group(6) = <TOTAL>-#.##
        #   m.group(7) = <SUBACCTSEC>CASH
        #   m.group(8) = <UNITS>#.###
        #   m.group(9) = <UNITPRICE>#.##
        #   m.group(10) = </REINVEST>
        p = re.compile(r'(<REINVEST>)(<.+?<MEMO>)(.+?[^<]*)(</INVTRAN>.+?<INCOMETYPE>)(.+?[^<]*)(<TOTAL>.+?[^<]*)(<SUBACCTSEC>.+?[^<]*)(<UNITS>.+?[^<]*)(<UNITPRICE>.+?[^<]*)(</REINVEST>)',re.IGNORECASE)
        m = p.match(ReinvTrans)

        gr01 = '<INCOME>'   #Change from <REINVEST>
        gr02 = m.group(2)
        gr04 = m.group(4)
        gr05 = m.group(5)
        if     gr05 == 'DIV'     : gr03 = 'DIVIDEND PAID'
        elif   gr05 == 'CGSHORT' : gr03 = 'SHORT TERM CAP GAIN PAID'
        elif   gr05 == 'CGLONG'  : gr03 = 'LONG TERM CAPITAL GAIN PAID'
        else : gr03 = m.group(3)    #Leave as reported
        gr06 = m.group(6).replace('-','')
        gr07 = m.group(7) + '<SUBACCTFUND>CASH'
        #No need to capture m.group(8) since it is deleted
        #No need to capture m.group(9) since it is deleted
        gr10 = '</INCOME>'
        PaidTrans = gr01+gr02+gr03+gr04+gr05+gr06+gr07+gr10

    if Debug: scrubPrint('Reinv Trans: '+ReinvTrans)
    if Debug: scrubPrint('Paid  Trans: '+PaidTrans)

    return PaidTrans             #return the new string for regex.sub()
    
# end t.rowe.price div reinvest scrubber
#-----------------------------------------------------------------------------

'''