#!python2

# GetData.py
# http://sites.google.com/site/pocketsense/
# retrieve statements, stock and fund data
# Intial version: rlc: Feb-2010

# History
# ---------
# 11-Mar-2010*rlc
#   - Added "interactive" mode
#   - Download all statements and quotes before beginning upload to Money
#   - Allow stock quotes to be sent to Money before statements (option defined in sites.dat) 
# 09-May-2010*rlc
#   - Download files in the order that they will be sent to Money so that file timestamps are in the same order
#   - Send data to Money using the os.system() call rather than os.startfile(), as this seems 
#     to help force the order when sending files to Money (FIFO)
#   - Added logic to catch failed connections and server timeouts
#   - Added "About" title and version to start
# 05-Sep-2010*rlc
#   - Updated to support spaces in SiteName values in sites.dat
#   - Don't auto-close command window if any error is detected during download operations
# 04-Jan-2011*rlc
#   - Display quotes.htm after download if "ShowQuoteHTM: Yes" defined in sites.dat
#   - Ask to display quotes.htm after download if "ShowQuoteHTM: Yes" defined in sites.dat (overrides ShowQuoteHTM)
# 18-Jan-2011*rlc
#   - Added 0.5 s delay between "file starts", which sends an OFX file to Money
# 23Aug2012*rlc
#   - Added user option to change default download interval at runtime
#   - Added support for combineOFX
# 28Aug2013*rlc
#   - Added support for forceQuotes option
# 21Oct2013*rlc
#   - Modified forceQuote option to prompt for statement accept in Money before continuing
# 25Feb2014*rlc
#   - Bug fix for forceQuote option when the quote feature isn't being used
# 14May2018*rlc
#   - If an a connection fails for a specific user/pw combo, don't try other accounts during the session
#     Added to help prevent accounts getting locked when a user changes their password, has multiple 
#     accounts at the institution, but forgot to update their account settings in Setup.
#16Sep2019*rlc
#   - Add support for ofx import from ./import subfolder.  any file present in ./import will be inspected,
#     and if it looks like a valid OFX file, will be processed the same as a downloaded statement (scrubbed, etc.)
#19Jun2023*rlc
#   - add logging

import os, sys, glob, time, re
import ofx, quotes, site_cfg, scrubber
from control2 import *
from rlib1 import *

#startup
print('')
userdat = site_cfg.site_cfg()
log = create_logger('root', 'getdata.log')
if Debug:
    log.warn("**DEBUG Enabled: See Control2.py to disable.")
    log.debug('xfrdir = %s' % xfrdir)

def getSite(ofx):
    # find matching site entry for ofx
    # matches on FID or BANKID value found in ofx and in sites list
    
    #get fid value from ofx
    site = None
    p = re.compile(r'<FID>(.*?)[<\s]',re.IGNORECASE | re.DOTALL)
    r = p.search(ofx)
    fid = r.groups()[0] if r else 'undefined'
    p = re.compile(r'<BANKID>(.*?)[<\s]',re.IGNORECASE | re.DOTALL)
    r = p.search(ofx)
    bankid = r.groups()[0] if r else 'undefined'
    sites = userdat.sites
    if fid or bankid:  
        for s in sites:
            if not site: site=sites[s]   #defaults to first site found, if matching fid/bankid not found
            thisFid    = FieldVal(sites[s], 'fid')
            thisBankid = FieldVal(sites[s], 'bankid')
            if thisFid == fid or thisBankid == bankid:
                site = sites[s]
                log.info('Matched import file to site *%s*' % s)
                break

    return site

if __name__=="__main__":

    stat1 = True    #overall status flag across all operations (true == no errors getting data)
    quotesExist = False
    print('')
    log.info(AboutTitle + ", Ver: " + AboutVersion)
    
    if Debug: 
        httpsVerify = False if os.environ.get('PYTHONHTTPSVERIFY','')=='0' else True
        log.debug('httpsVerify ' + 'ON' if httpsVerify else 'OFF')

    doit='Y'
    if userdat.promptStart:
        doit = input("Download transactions? (Y/N/I=Interactive) [Y] ").upper()
        doit = 'Y' if doit=='' else doit[:1]  #first char
    if doit in "YI":
        #get download interval, if promptInterval=Yes in sites.dat
        interval = userdat.defaultInterval
        if userdat.promptInterval:
            try:
                p = int2(input("Download interval (days) [" + str(interval) + "]: "))
                if p>0: interval = p
            except:
                log.info("Invalid entry. Using defaultInterval=" + str(interval))
        
        #get account info
        #AcctArray = [['SiteName', 'Account#', 'AcctType', 'UserName', 'PassWord'], ...]
        pwkey, getquotes, AcctArray = get_cfg()
        ofxList = []
        quoteFile1, quoteFile2, htmFileName = '','',''

        if len(AcctArray) > 0 and pwkey != '':
            #if accounts are encrypted... decrypt them
            pwkey=decrypt_pw(pwkey)
            AcctArray = acctDecrypt(AcctArray, pwkey)
    
        #delete old data files
        ofxfiles = xfrdir+'*.ofx'
        if glob.glob(ofxfiles) != []:
            os.system("del "+ofxfiles)
            
        log.info("Default download interval= {0} days".format(interval))
        
        #create process Queue in the right order
        Queue = ['Accts', 'importFiles']
        if userdat.savetickersfirst:
            Queue.insert(0,'Quotes')
        else:
            Queue.append('Quotes')

        for QEntry in Queue:

            if QEntry == 'Accts':
                if len(AcctArray) == 0:
                  log.info("No accounts have been configured. Run SETUP.PY to add accounts")

                #process accounts
                badConnects = []   #track [sitename, username] for failed connections so we don't risk locking an account
                for acct in AcctArray:
                    if [acct[0], acct[3]] not in badConnects:
                        status, ofxFile = ofx.getOFX(acct, interval)
                        if not status and userdat.skipFailedLogon: 
                            badConnects.append([acct[0], acct[3]])
                        else:
                            ofxList.append([acct[0], acct[1], ofxFile])
                        stat1 = stat1 and status
                        print("")
                
            if QEntry == 'importFiles':
                #process files from import folder [manual user downloaded files]
                #include anything that looks like a valid ofx file regardless of extension
                #attempts to find site entry by FID found in the ofx file
                
                log.info('Searching %s for statements to import' % importdir)
                for f in glob.glob(importdir+'*.*'):
                    fname = os.path.basename(f)   #full base filename.extension
                    bname = os.path.splitext(fname)[0]     #basename w/o extension
                    bext  = os.path.splitext(fname)[1]     #file extension
                    with open(f) as ifile:
                        dat = ifile.read()

                    #only import if it looks like an ofx file
                    if validOFX(dat) == '':
                        log.info("Importing %s" % fname)
                        if 'NEWFILEUID:PSIMPORT' not in dat[:200]:
                            #only scrub if it hasn't already been imported (and hence, scrubbed)
                            try:
                                site = getSite(dat)
                                scrubber.scrub(f, site)
                            except:
                                log.info('No site defined for %s in sites.dat: skipping scrub routines' % fname)
                                
                        
                        #set NEWFILEUID:PSIMPORT to flag the file as having already been imported/scrubbed
                        #don't want to accidentally scrub twice
                        with open(f, 'rU') as ifile:
                            ofx = ifile.read()
                        p = re.compile(r'NEWFILEUID:.*')
                        ofx2 = p.sub('NEWFILEUID:PSIMPORT', ofx)
                        if ofx2: 
                            with open(f, 'w') as ofile:
                                ofile.write(ofx2)
                        #preserve original file type but save w/ ofx extension
                        outname = xfrdir+fname + ('' if bext=='.ofx' else '.ofx')
                        os.rename(f, outname)
                        ofxList.append(['import file', '', outname])
                        log.info('%s saved to %s' % (fname, outname))

            #get stock/fund quotes
            if QEntry == 'Quotes' and getquotes:
                status, quoteFile1, quoteFile2, htmFileName = quotes.getQuotes()
                z = ['Stock/Fund Quotes','',quoteFile1]
                stat1 = stat1 and status
                if glob.glob(quoteFile1) != []: 
                    ofxList.append(z)
                else: quotesExist=False
                print("")

                # display the HTML file after download if requested to always do so
                if status and userdat.showquotehtm: os.startfile(htmFileName)                            

        if len(ofxList) > 0:
            log.info('Downloads completed.')
            verify = False
            gogo = 'Y'
            if userdat.combineofx and gogo != 'V':
                cfile=combineOfx(ofxList)       #create combined file

            if doit == 'I' or Debug:
                gogo = input('Upload results to Money? (Y/N/V=Verify) [Y] ').upper()
                gogo = 'Y' if gogo=='' else gogo[:1]    #first letter
            
            if gogo == 'N': log.info('Results not sent to Money.  User cancelled.')

            if gogo in 'YV':
                if glob.glob(quoteFile2) != []: 
                    if Debug: log.debug("Importing ForceQuotes statement: %s" % quoteFile2)
                    runFile(quoteFile2)  #force transactions for MoneyUK
                    input('ForceQuote statement loaded.  Accept in Money and press <Enter> to continue.')

                log.info('Sending statement(s) to Money...')
                if userdat.combineofx and cfile and gogo != 'V':
                    runFile(cfile)
                else:
                    for file in ofxList:
                        upload = True
                        if gogo == 'V':
                            #file[0] = site, file[1] = accnt#, file[2] = ofxFile
                            upload = (input('Upload ' + file[0] + ' : ' + file[1] + ' (Y/N) ').upper() == 'Y')
                            
                        if upload: 
                           log.info("Importing " + file[2])
                           runFile(file[2])
                        
                        time.sleep(0.5)   #slight delay, to force load order in Money

            #ask to show quotes.htm if defined in sites.dat
            if userdat.askquotehtm and quotesExist:
                ask = input('Open <Quotes.htm> in the default browser (y/n)?').upper()
                if ask=='Y': os.startfile(htmFileName)  #don't wait for browser close

            if userdat.promptEnd:
                input('\n\nPress <Enter> to continue...')
                    
        else:
            if len(AcctArray)>0 or (getquotes and len(userdat.stocks)>0):
                log.warn("No files were downloaded. Verify network connection and try again later.")
            input("Press <Enter> to continue...")
        
        if Debug:
            input("Press <Enter> to continue...")
        elif not stat1:
            log.warn( "One or more accounts (or quotes) may not have downloaded correctly.")
            input("Review and press <Enter> to continue...")
    
    log.info('-----------------------------------------------------------------------------------')
