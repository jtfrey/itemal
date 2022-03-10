#!/usr/bin/env python
#
# ITEM anALysis program
# Examination Services
# 
# Changelog:
#
#     1966-04       WALTER DICK
#     1967-10-31    R. KOHR: REVISED FORTRAN IV VERSION
#     1968-01-26
#     1968-01-31    CHANGED STANDARD FORMAT
#     1968-02-05
#     1968-02-08    CORRECTIONS  IN AVG. DIFFICULTY COMPUTATIONS
#     1968-02-24    ALLOWS 3-DIGIT SCORE FOR EACH OPT AVG
#     1970-01-12    R. KOHR: ADDED SUBROUTINE CONTRL
#     1985-08-09    R.S. SACHER:  CONVERTED TO IBM VSFORTRAN
#     2022-03-05    J.T. FREY:  CONVERTED TO PYTHON
#

import sys
import errno
import os
from datetime import datetime, date, time
import argparse
import re
import math
import json
import functools

#
# File formats recognized by the program:
#
formatsRecognized = {
        'fortran':      lambda statsData: FortranIOHelper(statsData),
        'json':         lambda statsData: JSONIOHelper(statsData),
        'json+pretty':  lambda statsData: JSONIOHelper(statsData, shouldIndentOutput=True)
    }

#
# To determine "is equal" for floating-point types, we need a function that calculates
# distance from zero -- anything within the given tolerance equates with equals.
#
# Python3 has a isclose() function in the math module.  If it's there, we alias isclose
# to that function.  If it's not present, we define our own isclose() function.
#
try:
    math.isclose(1.0, 1.0)
    isclose = math.isclose
except:
    def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
        return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


class SparseStorage(object):
    """The SparseStorage class implements a sparse multi-dimensional array.  The array starts as an empty list.  As data are added, the lists are filled-in to the necessary depth in each accessed dimension.  When data are read, any set of indices not leading to a set value produce a default return value, not an error.  This makes the multi-dimensional array essentially unbounded.  While the Fortran ITEMAL code is written to limit to 5 groups and 160 questions, the statistical data class uses SparseStorage and is thus not bound to any specific maximum dimensionality."""
    
    _allocIdx = 0
    
    @classmethod
    def allocIdx(cls):
        cls._allocIdx += 1
        return cls._allocIdx

    def __init__(self, rank, fillInValue=0):
        if rank < 1:
            raise ValueError('Invalid SparseStorage rank {:d}'.format(rank))
        self._storage = []
        self._rank = rank
        self._maxDimension = []
        self._allocIdx = SparseStorage.allocIdx()
        self._fillInValue = fillInValue
    
    def __getitem__(self, key):
        """Allow the convenience of bracket notation for getting the value at a key.  The key must be an list/tuple of the same dimension as the receiver's rank."""
        return self.valueAtIndex(key)
    
    def __setitem__(self, key, newValue):
        """Allow the convenience of bracket notation for setting the value at a key.  The key must be an list/tuple of the same dimension as the receiver's rank."""
        return self.setValueAtIndex(key, newValue)
    
    def maxDimension(self):
        return self._maxDimension
    
    def fillInValue(self):
        """Returns the fill-in value associated with unset regions of the receiver."""
        return self._fillInValue
    
    def setFillInValue(self, fillInValue=0):
        """Sets the fill-in value associated with unset regions of the receiver to fillInValue."""
        self._fillInValue = fillInValue
    
    def clearAllValues(self):
        """Reset the receiver to be completely empty of all set values."""
        self._storage = []
        self._maxDimension = []
    
    def valueAtIndex(self, key):
        """Return the value at the given key in the receiver.  The key must be an list/tuple of the same dimension as the receiver's rank (an IndexError exception will be thrown otherwise).  If the key is not set in the receiver, its fill-in value is returned."""
        if len(key) != self._rank:
            raise IndexError('Indices of rank {:d} where {:d} expected'.format(len(key), self._rank))
        outValue = self._fillInValue
        focus = self._storage
        try:
            for idx in key:
                focus = focus[idx]
            outValue = focus
        except:
            pass
        return outValue
    
    def setValueAtIndex(self, key, newValue=0):
        """Sets the value at the given key in the receiver to newValue.  The key must be an list/tuple of the same dimension as the receiver's rank (an IndexError exception will be thrown otherwise).  If the key is not set in the receiver, any intervening regions between the end of a list and the desired key will be filled with empty lists or the fill-in value (in the case of the final dimension)."""
        if len(key) != self._rank:
            raise IndexError('Indices of rank {:d} where {:d} expected'.format(len(key), self._rank))
        dimIdx = 0
        focus = self._storage
        for idx in key[:-1]:
            # Add a dimension?
            if dimIdx >= len(self._maxDimension):
                self._maxDimension.append(0)
            if idx >= len(focus):
                addEmptyLists = idx - len(focus) + 1
                if idx + 1 > self._maxDimension[dimIdx]:
                    self._maxDimension[dimIdx] = idx + 1
                for dummy in range(addEmptyLists):
                    focus.append([])
            focus = focus[idx]
            dimIdx += 1
        idx = key[-1]
        if idx >= len(focus):
            if dimIdx >= len(self._maxDimension):
                self._maxDimension.append(0)
            addEmptyItems = idx - len(focus) + 1
            if idx + 1 > self._maxDimension[dimIdx]:
                self._maxDimension[dimIdx] = idx + 1
            for dummy in range(addEmptyItems):
                focus.append(self._fillInValue)
        focus[idx] = newValue
    
    def addValueAtIndex(self, key, deltaValue):
        """Convenience method that fetches the value at the given key, adds deltaValue to it, and sets the value at that key to the sum."""
        self.setValueAtIndex(key, self.valueAtIndex(key) + deltaValue)
    
    def scaleValueAtIndex(self, key, multiplier):
        """Convenience method that fetches the value at the given key, multiplies by multiplier, and sets the value at that key to the product."""
        self.setValueAtIndex(key, self.valueAtIndex(key) * multiplier)


def stringToIntWithDefault(s, default=0):
    """Attempt to convert a string to an integer, returning the default value if the conversion fails."""
    try:
        return int(s)
    except:
        return default


def nextNonEmptyLineInFile(fptr):
    """Returns the next non-blank (whitespace only) line from the given file.  Raises EOFError when the end of file is reached."""
    while True:
        line = fptr.readline()
        if len(line) == 0:
            # End of file
            raise EOFError()
        if line.strip():
            break
    return line.rstrip()


class StudentData(object):
    """The StudentData class handles the storage of all test-taker answers.  Data entry are delimited by startRecord() and startGroup() functions.  The former begins a new answer list and score in the current group (creating one if none exist yet), and the latter creates a new group with no records.  With a record created, the setScore() and setAnswers()/appendAnswer()/appendAnswers() functions fill-in its data.

The data lists are meant to be accessed directly.  The scores list contains zero or more lists of test-taker scores (by group).  The answers list contains zero or more lists of lists of answers (integer values, by group).  Groups are created by default with an incrementing integer id, but any unique id can be provided to the startGroup() function.  The lists might look like this:

.scores = [ [20, 18], [15, 14, 14, 10], [5, 4, 3] ]
.answers = [ [ [1, 1, ..., 4], [1, 2, ..., 3] ], [ [2, 2, ..., 4], ... ], [ ... ] ]
.groupIds = [ 1, 2, 3 ]

Index -1 in each top-level list represents the last-added item.
"""

    def __init__(self, nItems):
        self.scores = []
        self.answers = []
        self.questionCount = nItems
        self.groupIds = []
        self._currentGroupId = None
        self._currentRecordId = None
    
    def currentGroupId(self):
        """Returns the id of the group to which records are currently being added.  If no groups/records have been added yet, None is returned."""
        return self._currentGroupId
    
    def currentRecordId(self):
        """Returns the id (in-list index) of the record currently being added.  If no record has been started yet, None is returned."""
        return self._currentRecordId
    
    def groupCount(self):
        """Returns the number of groups currently defined in the receiver."""
        return len(self.groupIds)
    
    def totalRecordCount(self):
        return functools.reduce(lambda sumCount, groupScores: sumCount + len(groupScores), self.scores, 0)
    
    def groupIndexForId(self, groupId):
        """Locate the given groupId and return the index occupied by it in the receiver's scores/answers/groupIds lists."""
        return self.groupIds.index(groupId)
    
    def startGroup(self, groupId=None):
        """Create a new record group.  If the currently-open group is empty, it is removed from the receiver.  If the groupId is None, the group id will be calculated as its 1-based index in the scores/answers/groupIds lists."""
        if self._currentGroupId is not None:
            if len(self.scores[-1]) > 0:
                # Check for None at end of score list, implying nothing was added, and remove the trailing empty lists from scores and answers:
                if self.scores[-1][-1] is None:
                    self.scores[-1].pop()
                    self.answers[-1].pop()
        if groupId is None:
            groupId = len(self.scores) + 1
            while groupId in self.groupIds:
                groupId = groupId + 1
        self.scores.append([])
        self.answers.append([])
        self.groupIds.append(groupId)
        self._currentGroupId = groupId
        self._currentRecordId = None
    
    def startRecord(self):
        """Create a new record.  If no group has been created yet, one is automatically added (and will use the default id generated by startGroup()).  The new record is empty of scores and answers."""
        if self._currentGroupId is None:
            self.startGroup()
        self.scores[-1].append(None)
        self.answers[-1].append([])
        self._currentRecordId = len(self.answers[-1]) - 1
    
    def score(self):
        """Returns the score of the current record.  If no record yet exists, one is created (and thus a group may be created, as well)."""
        if self._currentRecordId is None:
            self.startRecord()
        return self.scores[-1][-1]
    
    def setScore(self, score):
        """Set the score for the current record to score.  A score outside the range of valid responses throws a ValueError exception.  If no record yet exists, one is created (and thus a group may be created, as well)."""
        if self._currentRecordId is None:
            self.startRecord()
        if score > self.questionCount or score < 0:
            raise ValueError('Invalid score, {:d} out of {:d}'.format(score, self.questionCount))
        # Since the scores list has a terminal None appneded after a new record is started, this
        # record's score is always in the final index of the scores list.
        self.scores[-1][-1] = score
    
    def isAnswerListComplete(self):
        """Returns True if the current record has a full set of answers relative to the question count."""
        if self._currentRecordId is None:
            self.startRecord()
        return len(self.answers[-1][-1]) == self.questionCount
    
    def clearAnswers(self):
        """Remove all answers from the current record."""
        if self._currentRecordId is not None:
            self.startRecord()
        self.answers[-1][-1] = []
    
    def setAnswers(self, answers):
        """Set the current record's answers to the values in the (iterable) answers argument.  If no record yet exists, one is created (and thus a group may be created, as well).  If the incoming answers do not match the question count of the receiver, a ValueError exception is thrown."""
        if self._currentRecordId is None:
            self.startRecord()
        if len(answers) != self.questionCount:
            raise ValueError('Invalid answer list, {:d} < {:d} answers'.format(len(answers), self.questionCount))
        self.answers[-1][-1] = list(answers)
        
    def appendAnswer(self, addlAnswer):
        """Append the addlAnswer value to the current record's answers.  If no record yet exists, one is created (and thus a group may be created, as well).  If the answer list is already full, an IndexError exception is thrown."""
        if self._currentRecordId is None:
            self.startRecord()
        if len(self.answers[-1][-1]) >= self.questionCount:
            raise IndexError('Append to already-full answer list')
        self.answers[-1][-1].append(addlAnswer)
        
    def appendAnswers(self, addlAnswers):
        """Append the values in the (iterable) addlAnswers argument to the current record's answers.  If no record yet exists, one is created (and thus a group may be created, as well).  If the answer list will be overfilled by addlAnswers, a ValueError is thrown."""
        addlAnswerCount = len(addlAnswers)
        if addlAnswerCount > 0:
            if self._currentRecordId is None:
                self.startRecord()
            if len(self.answers[-1][-1]) + addlAnswerCount > self.questionCount:
                raise ValueError('Appending {:d} answers would overflow answer list of size {:d}'.format(addlAnswerCount), self.questionCount)
            self.answers[-1][-1].extend(addlAnswers)
    

class BaseIOHelper(object):
    """The BaseIOHelper forms the abstract subclass for all i/o helpers (Fortran, maybe dict coming from a YAML or JSON file in the future...)."""
    
    # The mapping of answers and questionability badge by index:
    answerSymbolByIndex = '$ ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    questionableBadgeByIndex = '$ ?'

    def __init__(self, statData):
        self.statData = statData
    
    def summarizeControlCard(self, outputFPtr):
        """After reading and initializing the test's metadata, this method is called to summarize that information to the outputFPtr."""
        raise NotImplementedError()
    
    def readHeader(self, inputFPtr, isContinued=False):
        """Read and initialize the test metadata for the receiver.  If isContinued is True, then the method should not expect a full header, just the key and format for additional answers that will follow for the same test.
        
Should return True if answers should be read, False if no further processing is necessary."""
        raise NotImplementedError()
    
    def readStudentData(self, inputFPtr, outputFPtr):
        """Create a new StudentData object and populate with test results read from inputFPtr.  A summary of the data is written to outputFPtr.
        
Returns a StudentData object containing the answers read."""
        raise NotImplementedError()
        
    def processTestResults(self):
        """Process the test statistics."""
        raise NotImplementedError()
    
    def printResults(self, inputFPtr, outputFPtr, studentData):
        """Write a statistical summary of the questions and answers to outputFPtr.  The inputFPtr is checked for an additional answer section or test.
        
Returns True if additional answers or another test are present in inputFPtr."""
        raise NotImplementedError()

    def fixupAnswerKey(self):
        """If the answers are in reverse order (IDIG = 2) then fixup their numerical order from (ICHO, ICHO-1, ..., 1) to (1, 2, ..., ICHO)."""
        if self.statData.IDIG == 2:
            self.statData.KORAN = [(self.statData.ICHO + 1 - i) for i in self.statData.KORAN]
        

class FortranIOHelper(BaseIOHelper):
    """The FortranIOHelper is a concrete subclass of the BaseIOHelper.  All of this code is a translation of the original Fortran code to Python (and the support functions/classes herein)."""

    # The student answers Fortran format string needs to be broken-down into (<COUNT>)?(I|T)<WIDTH> units:
    fieldRegex = re.compile('(\d+)?([IT])(\d+)')
    
    # The answer key will be printed by breaking the list into groups of this many values:
    answerKeyStride = 5
    
    # This is the answerKeyStride written out in all caps:
    answerKeyStrideStr = 'FIVE'
        
    def readHeader(self, inputFPtr, isContinued=False):
        if not isContinued:
            try:
                values = nextNonEmptyLineInFile(inputFPtr)
                
                #(I4,2A10,5X,3I2,1X,I4,2X,I3,3(4X,I1), I1,3X,I1 )
                self.statData.KTC = stringToIntWithDefault(values[0:4])         # 4-digit arbitrary id
                self.statData.COURS = values[4:14]                              # Course identifier
                self.statData.INST = values[14:24]                              # Instructor identifier
                self.statData.RAW_DATE = values[29:35]                          # Raw date MMDDYY with implied century
                
                ITN = stringToIntWithDefault(values[35:41])                     # Number of exam responses
                ITEMN = stringToIntWithDefault(values[41:46])                   # Number of questions on exam
                self.statData.setDimensions(ITN, ITEMN)
                
                self.statData.KODE = stringToIntWithDefault(values[46:51])      # 0 = test summary only, 1=question + test summary
                self.statData.ICHO = stringToIntWithDefault(values[51:56])      # Maximum number of responses per question
                self.statData.IDIG = stringToIntWithDefault(values[56:61])      # 1 = forward order (A, B, ...), 2 = reverse order (E, D, ...)
                self.statData.IUNT = stringToIntWithDefault(values[61:62])      # Fortran Unit from which to read test data (not useful...)
                self.statData.NCOPY = stringToIntWithDefault(values[62:])       # Number of copies (0, 1, 2)
                
            except Exception as E:
                # All done:
                return False
            
            # If that first field came back as zero, we're done with this file:
            if self.statData.KTC == 0:
                return False
                    
            # IDIG is the analysis mode and has 2 possible values:
            if self.statData.IDIG not in (1, 2):
                raise ValueError('0CURRENT VERSION ACCEPTS INPUT OPTION AS 1 OR 2 ONLY...USER SPECIFIED {:d}'.format(self.statData.IDIG))
            
            # Anywhere from 0 to 2 copies of the per-question analysis to be printed:
            if self.statData.NCOPY < 0:
                self.statData.NCOPY = 0
            elif self.statData.NCOPY > 2:
                self.statData.NCOPY = 2
            
            # Parse the raw date from the input file into a Python Date object:
            self.statData.DATE = datetime.strptime(self.statData.RAW_DATE, '%m%d%y')
        
        # Read correct answer card:
        nItems = self.statData.ITEMN
        self.statData.KORAN = []
        while nItems > 0:
            values = [int(x) for x in nextNonEmptyLineInFile(inputFPtr).strip()]
            self.statData.KORAN.extend(values)
            nItems = nItems - len(values)
            
        # Read the format card:
        self.FMTSTR = nextNonEmptyLineInFile(inputFPtr).strip()
        formatFields = self.FMTSTR.strip('()').split(',')
        self.FMT = []
        for field in formatFields:
            m = self.fieldRegex.match(field)
            if m is None:
                raise ValueError('Invalid field format: {:s}'.format(field))
            self.FMT.append({
                        'width': int(m.group(3)),
                        'count': int(m.group(1)) if m.group(1) else 1,
                        'type':  m.group(2)
                    })
        
        return True
        
    def summarizeControlCard(self, outputFPtr):
        #  210  FORMAT (' ',33X, 'ITEM ANALYSIS FOR DATA HAVING SPECIFIABLE RIGHT-
        #      1WRONG ANSWERS' ///// 33X, 'THE USER HAS SPECIFIED THE FOLLOWING IN
        #      2FORMATION ON CONTROL CARDS' //// 20X,'JOB NUMBER',I6 //20X,
        #      3 'COURSE  ',A10 //20X,'INSTRUCTOR  ',A10 //20X,'DATE (MONTH, DAY,
        #      4YEAR)  ',3I4  )
        outputFPtr.write(
                '                                  ITEM ANALYSIS FOR DATA HAVING SPECIFIABLE RIGHT-WRONG ANSWERS\n\n\n\n\n                                 THE USER HAS SPECIFIED THE FOLLOWING INFORMATION ON CONTROL CARDS\n\n\n\n                    JOB NUMBER{:6d}\n\n                    COURSE  {:10.10s}\n\n                    INSTRUCTOR  {:10.10s}\n\n                    DATE (MONTH, DAY, YEAR)  {:4d}{:4d}{:>4s}\n'.format(
                        self.statData.KTC, self.statData.COURS, self.statData.INST, self.statData.DATE.month, self.statData.DATE.day, self.statData.DATE.strftime('%y')))
                        
        #   220 FORMAT (/ 20X, 'NUMBER OF STUDENTS', I6  //20X,'NUMBER OF ITEMS',
        #      1 I5// 20X,'ITEM EVALUATION OPTION (0=NO, 1=YES)', I4 //20X,
        #      3 'MAXIMUM NUMBER OF ANSWER CHOICES', I4/)
        outputFPtr.write(
                '\n                    NUMBER OF STUDENTS{:6d}\n\n                    NUMBER OF ITEMS{:5d}\n\n                    ITEM EVALUATION OPTION (0=NO, 1=YES){:4d}\n\n                    MAXIMUM NUMBER OF ANSWER CHOICES{:4d}\n\n'.format(
                        self.statData.ITN, self.statData.ITEMN, self.statData.KODE, self.statData.ICHO))
        
        if self.statData.IDIG == 1:
            #  241  FORMAT (/25X,'INPUT FORMAT', 3X,A72 / 25X,'RESPONSE FORM  1=A, 2=
            #      1B, 3=C, ...ETC' )
            outputFPtr.write(
                    '\n                         INPUT FORMAT   {:72.72s}\n                         RESPONSE FORM  1=A, 2= B, 3=C, ...ETC\n'.format(self.FMTSTR))
        else:
            #  242  FORMAT (/25X,'INPUT FORMAT',3X, A72 / 25X,'RESPONSE FORM', I2,
            #      1 '=A,', I2,'=B, ...'  )
            outputFPtr.write(
                    '\n                         INPUT FORMAT   {:72.72s}\n                         RESPONSE FORM{:2d}=A,{:2d}=B, ...\n'.format(self.FMTSTR, self.statData.ICHO, self.statData.ICHO + 1))
        
        #  250  FORMAT (                             /20X,'NUMBER OF COPIES OF OUT
        #      1PUT (MAX. ALLOWED=2)', I3 //20X,'CORRECT ANSWERS IN GROUPS OF FIVE
        #      2' /2(25X,15(5I1,1X) /)  )
        outputFPtr.write(
                '\n                    NUMBER OF COPIES OF OUTPUT (MAX. ALLOWED=2){:3d}\n\n                    CORRECT ANSWERS IN GROUPS OF {:s}\n'.format(self.statData.NCOPY, self.answerKeyStrideStr))
        answerChunkCount = len(self.statData.KORAN)
        answerChunkCount = (answerChunkCount + (self.answerKeyStride - 1)) / self.answerKeyStride
        inRowMax = int(90 / (self.answerKeyStride + 1))
#        [''.join([str(c) for c in self.statData.KORAN[i:i+5]]) for i in range(0, len(self.statData.KORAN), 5)]
        answerChunkIdx = 0
        while answerChunkIdx < answerChunkCount:
            inRowIdx = 0
            outputFPtr.write('                         ')
            while answerChunkIdx < answerChunkCount and inRowIdx < inRowMax:
                outputFPtr.write('{:s}{:s}'.format(
                        ''.join([str(i) for i in self.statData.KORAN[answerChunkIdx * self.answerKeyStride:(answerChunkIdx + 1) * self.answerKeyStride]]),
                        (' ' if ((inRowIdx + 1 < inRowMax) and (answerChunkIdx + 1 < answerChunkCount)) else '\n'))
                    )
                answerChunkIdx += 1
                inRowIdx += 1
            
        outputFPtr.write('1\n')
    
    def parseStudentDataLine(self, studentDataLine, prevScore=None, prevAnswers=None):
        score = prevScore if (prevScore is not None) else None
        answers = prevAnswers if (prevAnswers is not None) else []
        lastIndex = 0
        fieldIndex = 0
        for field in self.FMT:
            if field['type'] == 'T':
                lastIndex = field['width'] - 1
            elif field['type'] == 'I':
                nItems = field['count']
                fieldWidth = field['width']
                while nItems > 0:
                    value = int(studentDataLine[lastIndex:lastIndex + fieldWidth])
                    if fieldIndex == 0:
                        # This should be the score or a -1 to indicate a new group:
                        if prevScore is None:
                            if value == -1:
                                # Signals a new group:
                                return (-1, None)
                            score = value
                        elif prevScore != value:
                            raise ValueError('Mismatched score {:d} vs. {:d} for multi-line student data at character {:d} in "{:s}"'.format(value, prevScore, lastIndex + 1, studentDataLine))
                    else:
                        answers.append(value)
                    # Processed a field, move to the next one:
                    lastIndex += fieldWidth
                    fieldIndex += 1
                    nItems -= 1
            else:
                raise ValueError('Invalid field type "{:s}" in "{:s}"'.format(field['type'], studentDataLine))
        
        return (score, answers)

    def readStudentData(self, inputFPtr, outputFPtr):
        outData = StudentData(self.statData.ITEMN)
        for dummy in range(self.statData.ITN):
            outData.startRecord()
            score = None
            answers = None
            while outData.groupCount() < 6 and not outData.isAnswerListComplete():
                (score, answers) = self.parseStudentDataLine(nextNonEmptyLineInFile(inputFPtr), score, answers)
                if score == -1:
                    # New group:
                    if outData.groupCount() < 6:
                        outData.startGroup()
                    score = None
                    answers = None
                else:
                    outData.setScore(score)
                    outData.appendAnswers(answers)
        
            if not outData.isAnswerListComplete():
                raise ValueError('Incomplete answer read from input file')
            
            l = outData.groupCount()
            self.statData.KOUNT[[l]] += 1
            self.statData.ISUM += outData.score()
            self.statData.ISUMSQ += (outData.score())**2
            if self.statData.IDIG == 2:
                for i in range(len(outData.answers[-1][-1]) ):
                    if outData.answer[-1][-1][i] != 0:
                        outData.answer[-1][-1][i] = self.statData.ICHO + 1 - outData.answer[-1][-1][i]
            for i in range(len(outData.answers[-1][-1])):
                if self.statData.KORAN[i] == outData.answers[-1][-1][i]:
                    self.statData.ICOUNT[[i + 1]] += 1
                    self.statData.ITC[[i + 1]] += outData.score()
                else:
                    self.statData.ITIC[[i + 1]] += outData.score()
                if outData.answers[-1][-1][i] < 0:
                    #   270 FORMAT (1H0,24HA RESPONSE FOR QUESTION ,I2,1X,10HFOR GROUP ,I1,1X,
                    #      116HREAD AS NEGATIVE)
                    outputFPtr.write(
                            'A RESPONSE FOR QUESTION {:2d} FOR GROUP {:1d} READ AS NEGATIVE'.format(i + 1, outData.currentGroupId()))
                    continue
                elif outData.answers[-1][-1][i] > self.statData.ICHO:
                    #   290 FORMAT (1H0,24HA RESPONSE FOR QUESTION ,I2,1X,10HFOR GROUP ,I1,1X,
                    #      121HREAD AS GREATER THAN ,I1)
                    outputFPtr.write(
                            'A RESPONSE FOR QUESTION {:2d} FOR GROUP {:1d} READ AS GREATER THAN {:1d}'.format(i + 1, outData.currentGroupId(), self.statDate.ICHO))
                    continue
                
                j = outData.answers[-1][-1][i] + 1
                self.statData.ITAB[[i + 1, j, l]] += 1
                self.statData.JTOT[[i + 1, j]] += 1
                self.statData.KSUM[[i + 1, j]] += outData.score()
                
        # Consume any remaining groups:
        while outData.groupCount() < 6:
            (score, answers) = self.parseStudentDataLine(nextNonEmptyLineInFile(inputFPtr))
            if score != -1:
                raise ValueError('Unable to consume group specified {:d} from input file'.format(self.groupCount() + 1))
            outData.startGroup()
            
        return outData
        
    def processTestResults(self, outputFPtr):
        self.statData.processTestResults()
        for message in self.statData.popMessages():
            outputFPtr.write('{:s}\n', message)
    
    def doLine60(self, outputFPtr, JUP):
        """Corresponds to GO TO line 60 in the original PRINT subroutine."""
        # '1',15X,'ITEM NUMBER',I4,8X,'CORRECT ANSWER AND ITEM DIFFICULTY INDEX ARE IDENTIFIED BY  * ' /
        outputFPtr.write('1               ITEM NUMBER{:4d}        CORRECT ANSWER AND ITEM DIFFICULTY INDEX ARE IDENTIFIED BY  * \n\n'.format(JUP))
        
    def doLine80(self, outputFPtr, JUP):
        """Corresponds to GO TO line 80 in the original PRINT subroutine."""
        # ' ',15X,'ITEM NUMBER',I4,8X,'CORRECT ANSWER AND ITEM DIFFICULTY INDEX ARE IDENTIFIED BY  * ' /
        outputFPtr.write('                ITEM NUMBER{:4d}        CORRECT ANSWER AND ITEM DIFFICULTY INDEX ARE IDENTIFIED BY  * \n\n'.format(JUP))

    def printResults(self, inputFPtr, outputFPtr, studentData):
        for copy in range(self.statData.NCOPY):
            L1 = 0
            L2 = 1
            JUP = self.statData.NNXYZ
            
            # Leftover debug kruft?
            outputFPtr.write('1\n')
            
            for i in range(1, self.statData.ITEMN + 1):
                JUP += 1
                KAN = self.statData.KORAN[i - 1]
                KOR = KAN + 1
                if self.statData.IDIG == 2:
                    KAN = self.statData.JCHO - KAN
                L1 += 1
                L2 += 1
                if i <= 2:
                    self.doLine80(outputFPtr, JUP)
                elif self.statData.ICHO <= 5:
                    if L2 <= 3:
                        self.doLine80(outputFPtr, JUP)
                    else:
                        self.doLine60(outputFPtr, JUP)
                        L1 = 1
                        L2 = 1
                elif L1 > 2:
                    self.doLine60(outputFPtr, JUP)
                    L1 = 1
                    L2 = 1
                else:
                    self.doLine80(outputFPtr, JUP)
                
                # '   OPTIONS',5X,'1ST',4X,'2ND',4X,'3RD',4X,'4TH',4X,'5TH',3X,'RESPONSE',4X,'PROPORTION',4X,'MEAN',6X,'OPTIONS'/ 14X,'GROUP',2X,'GROUP',2X,'GROUP',2X,'GROUP',2X,'GROUP',4X,'TOTAL',6X,'CHOOSING',5X,'SCORE',3X,'QUESTIONABLE'
                outputFPtr.write('   OPTIONS     1ST    2ND    3RD    4TH    5TH   RESPONSE    PROPORTION    MEAN      OPTIONS\n              GROUP  GROUP  GROUP  GROUP  GROUP    TOTAL      CHOOSING     SCORE   QUESTIONABLE\n')
                
                j = 1
                # 3X,'*',4HOMIT,5X,I3,4X,I3,4X,I3,4X,I3,4X,I3,5X,I4,8X,'*',F6.3,6X,F6.2
                # 1H ,3X,4HOMIT,5X,I3,4X,I3,4X,I3,4X,I3,4X,I3,5X,I4,9X,F6.3,6X,F6.2
                badge = ('*' if (KOR == j) else ' ')
                tallies = [self.statData.ITAB[[i, j, L]] for L in range(1,6)]
                outputFPtr.write('   {:s}OMIT     {:3d}    {:3d}    {:3d}    {:3d}    {:3d}     {:4d}        {:1s}{:6.3f}      {:6.2f}\n'.format(
                            badge,
                            tallies[0], tallies[1], tallies[2], tallies[3], tallies[4],
                            self.statData.JTOT[[i, j]], badge, self.statData.PROP[[i, j]], self.statData.CMEAN[[i, j]])
                        )
                
                JK = self.statData.JCHO
                for j in range(2, self.statData.JCHO + 1):
                    if self.statData.IDIG == 2:
                        JK -= 1
                        K = JK
                    else:
                        K = j - 1
                    IDIS = self.statData.IDIST[[i, j]]
                    
                    # 2X,'*',A1,' OR ',I1,4X,I3,4(4X,I3),5X,I4,8X,'*',F6.3,6X,F6.2,8X,A1
                    badge = ('*' if (KOR == j) else ' ')
                    tallies = [self.statData.ITAB[[i, j, L]] for L in range(1,6)]
                    outputFPtr.write('  {:s}{:1.1s} OR {:1d}    {:3d}    {:3d}    {:3d}    {:3d}    {:3d}     {:4d}        {:s}{:6.3f}      {:6.2f}        {:1.1s}\n'.format(
                            badge, self.answerSymbolByIndex[j], K,
                            tallies[0], tallies[1], tallies[2], tallies[3], tallies[4],
                            self.statData.JTOT[[i,j]], badge, self.statData.PROP[[i,j]], self.statData.CMEAN[[i, j]], self.questionableBadgeByIndex[IDIS])
                        )
                        
                # 1H0,2X,5HTOTAL,5X,I3,4X,I3,4X,I3,4X,I3,4X,I3,5X,I4
                counts = [self.statData.KOUNT[[j]] for j in range(1, 6)]
                outputFPtr.write('0  TOTAL     {:3d}    {:3d}    {:3d}    {:3d}    {:3d}     {:4d}\n'.format(
                        counts[0], counts[1], counts[2], counts[3], counts[4], self.statData.KTOT[[i]])
                    )
                
                # 1H0,'BISERIAL CORRELATION BETWEEN ITEM SCORE AND TOTAL SCORE ON TEST = ',F6.3
                outputFPtr.write('0BISERIAL CORRELATION BETWEEN ITEM SCORE AND TOTAL SCORE ON TEST = {:6.3f}\n'.format(
                        self.statData.BIS[[i]])
                    )
                
                # 1H ,29HPOINT-BISERIAL CORRELATION = ,F6.3,14X,4HT = ,F6.3///
                outputFPtr.write(' POINT-BISERIAL CORRELATION = {:6.3f}              T = {:6.3f}\n\n\n\n'.format(
                        self.statData.PBIS[[i]], self.statData.T[[i]])
                    )
                
                if self.statData.KODE == 0:
                    # 1H ,///
                    outputFPtr.write(' \n\n\n\n')
                
        self.statData.NNXYZ += self.statData.ITEMN
        for i in range(1, self.statData.ITEMN + 1):
            KEY = self.statData.KORAN[i - 1]
            self.statData.CNTKEY[[KEY]] += 1.0
            self.statData.PROSUM[[KEY]] += self.statData.PROP[[i, KEY + 1]]
            for j in range(2, self.statData.JCHO + 1):
                self.statData.CNTCHO[[j - 1]] += self.statData.TOT[[i, j]]
        self.statData.KTN = self.statData.ITN
        self.statData.KCHO = self.statData.ICHO
        self.statData.MCOPY = self.statData.NCOPY
        
        # Attempt to identify if there's another control card in the input file:
        values = nextNonEmptyLineInFile(inputFPtr)
        
        #(I4,2A10,5X,3I2,1X,I4,2X,I3,3(4X,I1), 1X,3X,I1 )
        ITEMN = stringToIntWithDefault(values[41:46])                   # Number of questions on exam
        if ITEMN > 0:
            # Also signals another set of answers
            self.statData.KTC = stringToIntWithDefault(values[0:4])         # 4-digit arbitrary id
            self.statData.COURS = values[4:14]                              # Course identifier
            self.statData.INST = values[14:24]                              # Instructor identifier
            self.statData.RAW_DATE = values[29:35]                          # Raw date MMDDYY with implied century
            ITN = stringToIntWithDefault(values[35:41])                     # Number of exam responses
            self.statData.setDimensions(ITN, ITEMN)
            self.statData.KODE = stringToIntWithDefault(values[46:51])      # 0 = test summary only, 1=question + test summary
            self.statData.ICHO = stringToIntWithDefault(values[51:56])      # Maximum number of responses per question
            self.statData.IDIG = stringToIntWithDefault(values[56:61])      # 1 = forward order (A, B, ...), 2 = reverse order (E, D, ...)
            self.statData.NCOPY = stringToIntWithDefault(values[62:])       # Number of copies (0, 1, 2)
            
            return True
        
        # Parse the raw date from the input file into a Python Date object:
        self.statData.DATE = datetime.strptime(self.statData.RAW_DATE, '%m%d%y')
        
        # Calculation aggregate statistics across all sections:
        self.statData.calculateAggregateStats()
        
        for dummy in range(self.statData.NCOPY):
            # '1',50X,'ADDITIONAL TEST INFORMATION'//// 15X,'THE MEAN ITEM DIFFICULTY FOR THE ENTIRE TEST =',F7.3//15X,'THE MEAN ITEM SCORE - TOTAL SCORE BISERIAL CORRELATION =', F6.3
            outputFPtr.write('1                                                  ADDITIONAL TEST INFORMATION\n\n\n\n               THE MEAN ITEM DIFFICULTY FOR THE ENTIRE TEST ={:7.3f}\n\n               THE MEAN ITEM SCORE - TOTAL SCORE BISERIAL CORRELATION ={:6.3f}\n'.format(
                    self.statData.FMEDI, self.statData.FMEBIS)
                )
        
            # /15X,'KUDER-RICHARDSON 20 RELIABILITY =',F7.3//  15X,'TEST MEAN =',F7.2, '   VARIANCE =', F10.2,  '   STANDARD DEVIATION =',F7.2 /
            outputFPtr.write('\n               KUDER-RICHARDSON 20 RELIABILITY ={:7.3f}\n\n               TEST MEAN ={:7.2f}   VARIANCE ={:10.2f}   STANDARD DEVIATION ={:7.2f}\n\n'.format(
                    self.statData.REL, self.statData.FMEAN, self.statData.FVAR, self.statData.SDEV)
                )
        
            # 15X,'STANDARD ERROR OF MEASUREMENT (BASED ON KR-20) =',F7.2//  15X,'NUMBER OF STUDENTS =',I5,8X,'NUMBER OF ITEMS ON TEST =',I5////
            outputFPtr.write('               STANDARD ERROR OF MEASUREMENT (BASED ON KR-20) ={:7.2f}\n\n               NUMBER OF STUDENTS ={:5d}        NUMBER OF ITEMS ON TEST ={:5d}\n\n\n\n\n'.format(
                    self.statData.SEMEAS, self.statData.KTN, self.statData.ITITEM)
                )
        
            # ' ',10X,'DISTRIBUTION OF THE TEST ITEMS',39X,'DISTRIBUTION OF THE TEST ITEMS'/ ' IN TERMS OF THE PERCENTAGE OF STUDENTS',' PASSING THEM', 14X,'IN TERMS OF ITEM SCORE - TOTAL SCORE BISERIAL CORRELATIONS'/// 6X,'PERCENT PASSING',11X,'NUMBER OF ITEMS',33X, 'CORRELATIONS', 4X,'NUMBER OF ITEMS'
            outputFPtr.write('           DISTRIBUTION OF THE TEST ITEMS                                       DISTRIBUTION OF THE TEST ITEMS\n')
            outputFPtr.write(' IN TERMS OF THE PERCENTAGE OF STUDENTS PASSING THEM              IN TERMS OF ITEM SCORE - TOTAL SCORE BISERIAL CORRELATIONS\n\n\n')
            outputFPtr.write('      PERCENT PASSING           NUMBER OF ITEMS                                 CORRELATIONS    NUMBER OF ITEMS\n')
        
            # '0',10X,'0 - 19',20X,I3,39X,'NEGATIVE - .10',8X,I3)
            outputFPtr.write('0          0 - 19                    {:3d}                                       NEGATIVE - .10        {:3d}\n'.format(
                    self.statData.IDO, self.statData.IDVP)
                )
        
            # ' ',9X,'20 - 39',20X,I3,42X,'.11 - .30',10X,I3)
            outputFPtr.write('          20 - 39                    {:3d}                                          .11 - .30          {:3d}\n'.format(
                    self.statData.IDTW, self.statData.IDP)
                )
        
            # ' ',9X,'40 - 59',20X,I3,42X,'.31 - .50',10X,I3)
            outputFPtr.write('          40 - 59                    {:3d}                                          .31 - .50          {:3d}\n'.format(
                    self.statData.IDTH, self.statData.IDG)
                )
        
            # ' ',9X,'60 - 79',20X,I3,42X,'.51 - .70',10X,I3)
            outputFPtr.write('          60 - 79                    {:3d}                                          .51 - .70          {:3d}\n'.format(
                    self.statData.IDFO, self.statData.IDVG)
                )
        
            # ' ',9X,'80 -100',20X,I3,42X,'.71 - .90',10X,I3
            outputFPtr.write('          80 -100                    {:3d}                                          .71 - .90          {:3d}\n'.format(
                    self.statData.IDFI, self.statData.IDVVG)
                )
            
            # ' ',81X,'.91 -    ',10X,I3/ ////40X,'CHOICES',5X,'% KEYED',5X,'% CHOSEN',5X,'AVG. DIFF.'  /
            outputFPtr.write('                                                                                  .91 -              {:3d}\n\n\n\n\n                                        CHOICES     % KEYED     % CHOSEN     AVG. DIFF.\n\n'.format(
                    self.statData.IDEX)
                )
        
            for k in range(1, self.statData.KCHO + 1):
                # (43X,A1,9X,F5.3,8X,F5.3,9X,F5.3)
                outputFPtr.write('                                           {:1.1s}         {:5.3f}        {:5.3f}         {:5.3f}\n'.format(
                        self.answerSymbolByIndex[k + 1], self.statData.PCTKEY[[k]], self.statData.PCTCHO[[k]], self.statData.AVDIFF[[k]])
                    )
        
            # //10X,'% KEYED= FREQUENCY OF A GIVEN KEY DIVIDED BY THE NUMBER OF ITEMS.'/ 10X,'% CHOSEN= FREQUENCY OF A GIVEN RESPONSE DIVIDED BY THE TOTAL NUMBER OF RESPONSES TO ALL ITEMS (EXCLUDING OMITS).'/ 10X,'AVG. DIFF.= TOTAL OF ALL DIFFICULTY VALUES FOR ITEMS WITH A GIVEN KEY DIVIDED BY THE NUMBER OF SUCH ITEMS.'
            outputFPtr.write('\n\n          % KEYED= FREQUENCY OF A GIVEN KEY DIVIDED BY THE NUMBER OF ITEMS.\n')
            outputFPtr.write('          % CHOSEN= FREQUENCY OF A GIVEN RESPONSE DIVIDED BY THE TOTAL NUMBER OF RESPONSES TO ALL ITEMS (EXCLUDING OMITS).\n')
            outputFPtr.write('          AVG. DIFF.= TOTAL OF ALL DIFFICULTY VALUES FOR ITEMS WITH A GIVEN KEY DIVIDED BY THE NUMBER OF SUCH ITEMS.\n')
        
        return False


class JSONIOHelper(BaseIOHelper):
    """The JSONIOHelper is a concrete subclass of the BaseIOHelper.  All data is read from a JSON file."""
    
    def __init__(self, statData, shouldIndentOutput=False):
        self._dataSet = None
        self._questionSetIndex = None
        self._messages = []
        self._outputDoc = {}
        self._shouldIndentOutput = shouldIndentOutput
        super(JSONIOHelper, self).__init__(statData)
    
    def dataSet(self):
        return self._dataSet
    
    def setDataSet(self, dataSet):
        if self._dataSet is not None:
            raise RuntimeError('Cannot overwrite existing read-in data set')
        self._dataSet = dataSet
    
    def readInputFile(self, inputFPtr):
        return json.load(inputFPtr)

    def initializeOptionsFromDict(self, optionsDict):
        if 'testSummaryOnly' in optionsDict:
            self.statData.KODE = 0 if optionsDict['testSummaryOnly'] else 1
        if 'isReverseOrder' in optionsDict:
            self.statData.IDIG = 2 if optionsDict['isReverseOrder'] else 1
        if 'numberOfCopies' in optionsDict:
            ncopy = int(optionsDict['numberOfCopies'])
            self.statData.NCOPY = 2 if (ncopy >= 2) else (0 if (ncopy <= 0) else ncopy)
    
    def initializeMetaDataFromDict(self, headerDict, isPrimary=False):
        if isPrimary:
            self.statData.KTC = headerDict.get('examId', 0)
            if self.statData.KTC == 0:
                return False
        
            self.statData.RAW_DATE = headerDict.get('date', date.today())
            if isinstance(self.statData.RAW_DATE, str) or isinstance(self.statData.RAW_DATE, unicode):
                try:
                    self.statData.DATE = datetime.strptime(self.statData.RAW_DATE, '%m%d%y')
                except:
                    try:
                        self.statData.DATE = datetime.strptime(self.statData.RAW_DATE, '%Y-%m-%d')
                    except:
                        try:
                            pieces = self.statData.RAW_DATE.split('T')
                            self.statData.DATE = datetime.strptime(pieces[0], '%Y-%m-%d')
                        except:
                            try:
                                self.statData.DATE = datetime.strptime(self.statData.RAW_DATE, '%x')
                            except:
                                raise ValueError('Invalid test date supplied: {:s}'.format(self.statData.RAW_DATE))
            else:
                self.statData.DATE = self.statData.RAW_DATE
                self.statData.RAW_DATE = date.strftime(self.statData.DATE, '%Y-%m-%d')
        
            self.statData.COURS = headerDict.get('course', '')
            self.statData.INST = headerDict.get('instructor', '')
            self.statData.KODE = 1
            self.statData.IDIG = 1
            self.statData.NCOPY = 1
        if 'options' in headerDict:
            self.initializeOptionsFromDict(headerDict['options'])
        return True
    
    def initializeAnswerKeyFromDict(self, answerKey, answerRange=None):
        self.statData.setDimensions(ITEMN=len(answerKey))
        self.statData.KORAN = [int(i) for i in answerKey]  if (isinstance(answerKey, str) or isinstance(answerKey, unicode)) else answerKey
        self.statData.ICHO = (max(self.statData.KORAN) - min(self.statData.KORAN) + 1) if answerRange is None else int(answerRange)
    
    def readHeaderFromDict(self, dataSet, isPrimary=False):
        if isPrimary:
            if not self.initializeMetaDataFromDict(dataSet, isPrimary=True):
                return False
            self.setDataSet(dataSet)
            
            # Do we have question sets?
            if not 'questionSets' in dataSet:
                raise ValueError('Exam data lacks questionSets array!')
            self._questionSetIndex = 0

        # Set current focus to the first question set:
        if self._questionSetIndex < len(self._dataSet['questionSets']):
            questionSet = self._dataSet['questionSets'][self._questionSetIndex]
        
            # Fixup meta-data:
            if not isPrimary and not self.initializeMetaDataFromDict(questionSet, isPrimary=False):
                return False
        
            # Correct answers:
            if 'answerKey' not in questionSet:
                raise ValueError('Question set {:d} lacks an answerKey'.format(self._questionSetIndex))
            self.initializeAnswerKeyFromDict(questionSet['answerKey'], questionSet.get('answerRange', None))
        
            if 'options' in questionSet:
                self.initializeOptionsFromDict(questionSet['options'])
        
            return True
        return False
        
    def readHeader(self, inputFPtr, isContinued=False):
        if not isContinued:
            dataSet = self.readInputFile(inputFPtr)
            headerResult = self.readHeaderFromDict(dataSet, isPrimary=True)
            if headerResult:
                self._outputDoc['course'] = self.statData.COURS
                self._outputDoc['instructor'] = self.statData.INST
                self._outputDoc['examDate'] = datetime.strftime(self.statData.DATE, '%Y-%m-%d')
                self._outputDoc['processedTimestamp'] = datetime.strftime(datetime.now(), '%Y-%m-%dT%H:%M:%S')
                self._outputDoc['results'] = []
            return headerResult
        else:
            self._questionSetIndex += 1
            if self._questionSetIndex < len(self._dataSet['questionSets']):
                return self.readHeaderFromDict(self._dataSet['questionSets'][self._questionSetIndex], isPrimary=False)
        return False
        
    def initializeStudentDataFromCurrentQuestionSet(self):
        if self._questionSetIndex is None or self._questionSetIndex >= len(self._dataSet['questionSets']):
            return False
        
        outData = StudentData(self.statData.ITEMN)
        for group in self._dataSet['questionSets'][self._questionSetIndex]['responses']:
            outData.startGroup(groupId=group.get('group', None))
            for studentAnswers in group['answers']:
                studentAnswers = [int(i) for i in studentAnswers]  if (isinstance(studentAnswers, str) or isinstance(studentAnswers, unicode))  else studentAnswers
                if len(studentAnswers) != self.statData.ITEMN:
                    raise ValueError('Invalid response item "{:s}":  {:d} answers should be {:d}'.format(str(studentAnswers), len(studentAnswers), self.statData.ITEMN))
                
                # Add a new record:
                outData.startRecord()
                
                # Calcuate the score:
                score = functools.reduce(lambda a, b: a + b, [0 if (a != b) else 1 for (a, b) in zip(studentAnswers, self.statData.KORAN)])
                
                self.statData.KOUNT[[outData.groupCount()]] += 1
                self.statData.ISUM += score
                self.statData.ISUMSQ += score**2
                if self.statData.IDIG == 2:
                    for i in range(len(studentAnswers) ):
                        if studentAnswers[i] != 0:
                            studentAnswers[i] = self.statData.ICHO + 1 - studentAnswers[i]
                
                # Set the score and answers:
                outData.setScore(score)
                outData.setAnswers(studentAnswers)
                
                for i in range(len(studentAnswers)):
                    if self.statData.KORAN[i] == studentAnswers[i]:
                        self.statData.ICOUNT[[i + 1]] += 1
                        self.statData.ITC[[i + 1]] += score
                    else:
                        self.statData.ITIC[[i + 1]] += score
                    if studentAnswers[i] < 0:
                        self._messages.append('Response for question {:d} for group {:s} is negative.'.format(i, str(outData.currentGroupId())))
                        continue
                    elif studentAnswers[i] > self.statData.ICHO:
                        self._messages.append('Response for question {:d} for group {:s} exceeds possible answers {:d}.'.format(i, str(outData.currentGroupId()), self.statData.ICHO))
                        continue
                    
                    j = studentAnswers[i] + 1
                    self.statData.ITAB[[i + 1, j, outData.groupCount()]] += 1
                    self.statData.JTOT[[i + 1, j]] += 1
                    self.statData.KSUM[[i + 1, j]] += score
                    
        self.statData.setDimensions(ITN=outData.totalRecordCount())
        return outData
            
    def readStudentData(self, inputFPtr, outputFPtr):
        outData = self.initializeStudentDataFromCurrentQuestionSet()
        if len(self._messages):
            for msg in self._messages:
                sys.stderr.write('WARNING:  ' + msg + '\n')
            self._messages = []
        if not outData:
            raise RuntimeError('Failed reading student data.')
        return outData
        
    def summarizeControlCard(self, outputFPtr):
        section = {
                'responseForm': 'forward' if (self.statData.IDIG == 1) else 'reverse',
                'answerKey': self.statData.KORAN,
                'summaries': []
            }
        self._outputDoc['results'].append(section)
        
    def processTestResults(self, outputFPtr):
        self.statData.processTestResults()
        for message in self.statData.popMessages():
            sys.stderr.write('ERROR:  In test result processing: {:s}\n', message)
    
    def processResultSetForData(self, studentData):

        # To which result set are we adding this stuff?
        resultSet = self._outputDoc['results'][-1]
        
        # Should we add per-question summaries to the doc?
        JUP = self.statData.NNXYZ
        
        for i in range(1, self.statData.ITEMN + 1):
            JUP += 1
            KAN = self.statData.KORAN[i - 1]
            KOR = KAN + 1
            if self.statData.IDIG == 2:
                KAN = self.statData.JCHO - KAN
            
            questionSummary = {
                    'questionNumber': JUP,
                    'correctAnswer': KOR,
                    'biserialCorrelation': self.statData.BIS[[i]],
                    'pointBiserialCorrelation': self.statData.PBIS[[i]],
                    'T': self.statData.T[[i]],
                    'byAnswer': {
                        'OMIT': {
                            'proportionChoosing': self.statData.PROP[[i, 1]],
                            'answerIndex': 0,
                            'meanScore': self.statData.CMEAN[[i, 1]],
                            'responseTotal': self.statData.JTOT[[i, 1]],
                            'isQuestionable': False,
                            'perGroupResponseCounts': [self.statData.ITAB[[i, 1, L]] for L in range(1, studentData.groupCount() + 1)]
                        }
                    }
                }
            JK = self.statData.JCHO
            for j in range(2, self.statData.JCHO + 1):
                if self.statData.IDIG == 2:
                    JK -= 1
                    K = JK
                else:
                    K = j - 1
                questionSummary['byAnswer'][self.answerSymbolByIndex[j]] = {
                        'proportionChoosing': self.statData.PROP[[i, j]],
                        'answerIndex': K,
                        'meanScore': self.statData.CMEAN[[i, j]],
                        'responseTotal': self.statData.JTOT[[i, j]],
                        'isQuestionable': True if (self.statData.IDIST[[i, j]] == 2) else False,
                        'perGroupResponseCounts': [self.statData.ITAB[[i, j, k]] for k in range(1, studentData.groupCount() + 1)]
                    }
        
            resultSet['summaries'].append(questionSummary)
        
        self.statData.NNXYZ += self.statData.ITEMN
        for i in range(1, self.statData.ITEMN + 1):
            KEY = self.statData.KORAN[i - 1]
            self.statData.CNTKEY[[KEY]] += 1.0
            self.statData.PROSUM[[KEY]] += self.statData.PROP[[i, KEY + 1]]
            for j in range(2, self.statData.JCHO + 1):
                self.statData.CNTCHO[[j - 1]] += self.statData.TOT[[i, j]]
        self.statData.KTN = self.statData.ITN
        self.statData.KCHO = self.statData.ICHO
        self.statData.MCOPY = self.statData.NCOPY

    def processAggregateStatistics(self):
        # Calculation aggregate statistics across all sections:
        self.statData.calculateAggregateStats()
        
        # Begin filling-in the aggregate results dictionary:
        aggResults = {
                'meanQuestionDifficulty': self.statData.FMEDI,
                'biserialCorrelation': self.statData.FMEBIS,
                'kuderRichardson20Reliability': self.statData.REL,
                'testMean': self.statData.FMEAN,
                'variance': self.statData.FVAR,
                'standardDeviation': self.statData.SDEV,
                'standardErrorOfMeasurementKR20': self.statData.SEMEAS,
                'numberOfStudents': self.statData.KTN,
                'numberOfQuestions': self.statData.ITITEM,
                
                'answerFrequencyBreakdown': {
                        self.answerSymbolByIndex[k + 1]: {
                               'frequencyPerQuestion': self.statData.PCTKEY[[k]],
                               'frequencyPerResponse': self.statData.PCTCHO[[k]],
                               'averageDifficulty': self.statData.AVDIFF[[k]]
                            } for k in range(1, self.statData.KCHO + 1)
                    },
                    
                'distributionByPassingStatus': [
                        { 'range': [0, 19], 'numberOfItems': self.statData.IDO },
                        { 'range': [20, 39], 'numberOfItems': self.statData.IDTW },
                        { 'range': [40, 59], 'numberOfItems': self.statData.IDTH },
                        { 'range': [60, 79], 'numberOfItems': self.statData.IDFO },
                        { 'range': [80, 100], 'numberOfItems': self.statData.IDFI }
                    ],
                
                'distributionByScore': [
                        { 'range': ['-Infinity', 0.10], 'numberOfItems': self.statData.IDVP },
                        { 'range': [0.11, 0.30], 'numberOfItems': self.statData.IDP },
                        { 'range': [0.31, 0.50], 'numberOfItems': self.statData.IDG },
                        { 'range': [0.51, 0.70], 'numberOfItems': self.statData.IDVG },
                        { 'range': [0.71, 0.90], 'numberOfItems': self.statData.IDVVG },
                        { 'range': [0.91, '+Infinity'], 'numberOfItems': self.statData.IDEX }
                    ]
            }
        
        self._outputDoc['aggregateResults'] = aggResults

    def printResultsCommonCode(self, studentData):
        self.processResultSetForData(studentData)
        
        # Are there more question sets present?
        if self._questionSetIndex + 1 < len(self._dataSet['questionSets']):
            return True
        
        self.processAggregateStatistics()
        return False

    def printResults(self, inputFPtr, outputFPtr, studentData):
        if self.printResultsCommonCode(studentData):
            return True
            
        if self._shouldIndentOutput:
            json.dump(self._outputDoc, outputFPtr, indent=4)
        else:
            json.dump(self._outputDoc, outputFPtr)
        outputFPtr.write('\n')
        return False
        
        
try:
    #
    # Attempt to load the PyYAML library into this namespace.  If successful, then create the YAMLIOHelper
    # subclass of the JSONIOHelper class (which is REALLY simple) and register it as a recognized format.
    from yaml import load as yamlLoad, dump as yamlDump
    try:
        from yaml import CLoader as yamlLoader, CDumper as yamlDumper
    except ImportError:
        from yaml import Loader as yamlLoader, Dumper as yamlDumper


    class YAMLIOHelper(JSONIOHelper):
        """The YAMLIOHelper is a subclass of the JSONIOHelper.  All data is read from a YAML file."""
        
        def readInputFile(self, inputFPtr):
            return yamlLoad(inputFPtr, Loader=yamlLoader)

        def printResults(self, inputFPtr, outputFPtr, studentData):
            if self.printResultsCommonCode(studentData):
                return True
            
            yamlDump(self._outputDoc, stream=outputFPtr, Dumper=yamlDumper, indent=4)
            return False

    # Register the constructor in the formatsRecognized dictionary:
    formatsRecognized['yaml'] = lambda statsData: YAMLIOHelper(statsData)

except:
    pass
    

class StatData:
    """Class that wraps all of the common blocks and data processing present in the original Fortran code."""
    
    CHEK = [ 0.2, 0.2, 0.1, 0.07, 0.05, 0.04, 0.04, 0.04, 0.04 ]
    
    def __init__(self):
        """Initialization of the statistical data object fields' that only change across input files."""
        self.NNXYZ = 0
        self.GITEMN = 0.0
        self.VAR = 0.0
        self.SBIS = 0.0
        self.SDI = 0.0
        self.IDO = 0
        self.IDTW = 0
        self.IDTH = 0
        self.IDFO = 0
        self.IDFI = 0
        self.IDVP = 0
        self.IDG = 0
        self.IDP = 0
        self.IDVG = 0
        self.IDVVG = 0
        self.IDEX = 0
        self.CNTKEY = SparseStorage(rank=1, fillInValue=0.0)
        self.PROSUM = SparseStorage(rank=1, fillInValue=0.0)
        self.CNTCHO = SparseStorage(rank=1, fillInValue=0.0)
        self.KORAN = None
        
        self.FKSUM = SparseStorage(rank=2, fillInValue=0.0)
        self.CMEAN = SparseStorage(rank=2, fillInValue=0.0)
        self.PROP = SparseStorage(rank=2, fillInValue=0.0)
        self.TOT = SparseStorage(rank=2, fillInValue=0.0)
        
        self.AVDIFF = SparseStorage(rank=1, fillInValue=0.0)
        self.BIS = SparseStorage(rank=1, fillInValue=0.0)
        self.DIFI = SparseStorage(rank=1, fillInValue=0.0)
        self.FCOUNT = SparseStorage(rank=1, fillInValue=0.0)
        self.FITC = SparseStorage(rank=1, fillInValue = 0.0)
        self.FITIC = SparseStorage(rank=1, fillInValue = 0.0)
        self.PBIS = SparseStorage(rank=1, fillInValue=0.0)
        self.PCTCHO = SparseStorage(rank=1, fillInValue=0.0)
        self.PCTKEY = SparseStorage(rank=1, fillInValue=0.0)
        self.Q = SparseStorage(rank=1, fillInValue=0.0)
        self.QCOUNT = SparseStorage(rank=1, fillInValue=0.0)
        self.T = SparseStorage(rank=1, fillInValue=0.0)
        self.Y = SparseStorage(rank=1, fillInValue=0.0)
        
        self._messages = []
    
    def setDimensions(self, ITN=None, ITEMN=None):
        if ITN is not None:
            self.ITN = ITN
            self.FITN = float(self.ITN)
        if ITEMN is not None:
            self.ITEMN = ITEMN
            self.FITEMN = float(self.ITEMN)
            self.GITEMN = self.GITEMN + self.FITEMN
        
    
    def prepForDataRead(self):
        """Initialize statistical data object fields that get reset before student data are read."""
        self.ISUMSQ = 0
        self.ISUM = 0
        self.SER = 0.0
        self.SDEV = 0.0
        
        self.ITAB = SparseStorage(rank=3, fillInValue=0)
        self.KSUM = SparseStorage(rank=2, fillInValue=0)
        self.JTOT = SparseStorage(rank=2, fillInValue=0)
        self.IDIST = SparseStorage(rank=2, fillInValue=0)
        self.KOUNT = SparseStorage(rank=1, fillInValue=0)
        self.ICOUNT = SparseStorage(rank=1, fillInValue=0)
        self.IBI = SparseStorage(rank=1, fillInValue=0)
        self.IDI = SparseStorage(rank=1, fillInValue=0)
        self.ITC = SparseStorage(rank=1, fillInValue=0)
        self.FMNCO = SparseStorage(rank=1, fillInValue=0.0)
        self.FMNIC = SparseStorage(rank=1, fillInValue=0.0)
        self.ITIC = SparseStorage(rank=1, fillInValue=0)
        self.KTOT = SparseStorage(rank=1, fillInValue=0)
        
        self.JCHO = self.ICHO + 1
    
    def popMessages(self):
        """Return all accumulated messages and reset the message list to empty."""
        out = self._messages
        self._messages = []
        return out
    
    def doLine570(self, i):
        """Corresponds to GO TO line 570 in the original Fortran code."""
        self.BIS[[i]] = 0.0
        self.PBIS[[i]] = 0.0
        self.T[[i]] = 0.0
    
    def doLine610(self, i, area):
        """Corresponds to GO TO line 610 in the original Fortran code."""
        eta = math.sqrt(math.log(1.0 / area**2))
        abcissa = eta - ((2.30753 + 0.27061 * eta) / (1.0 + 0.99229 * eta + 0.04481 * eta**2))
        self.Y[[i]] = 0.3989422 * (1.0 / (2.7182818**(abcissa**2 / 2.0)))
        self.doLine620(i)
    
    def doLine620(self, i):
        """Corresponds to GO TO line 620 in the original Fortran code."""
        self.FITC[[i]] = self.ITC[[i]]
        self.FITIC[[i]] = self.ITIC[[i]]
        self.FMNCO[[i]] = self.FITC[[i]] / self.FCOUNT[[i]]
        self.QCOUNT[[i]] = self.FITN - self.FCOUNT[[i]]
        self.FMNIC[[i]] = self.FITIC[[i]] / self.QCOUNT[[i]]
        self.Q[[i]] = 1.0 - self.DIFI[[i]]
        self.VAR = self.VAR + (self.DIFI[[i]] * self.Q[[i]])
        if isclose(self.SDEV, 0.0):
            self.doLine632(i)
        else:
            self.BIS[[i]] = ((self.FMNCO[[i]] - self.FMNIC[[i]]) / self.SDEV) * self.DIFI[[i]] * self.Q[[i]] / self.Y[[i]]
            self.PBIS[[i]] = self.BIS[[i]] * (self.Y[[i]] / math.sqrt(self.DIFI[[i]] * self.Q[[i]]))
            self.T[[i]] = self.PBIS[[i]] * math.sqrt((self.FITN - 2.0) / (1.0 - self.PBIS[[i]]**2))
            self.doLine630(i)
    
    def doLine630(self, i):
        """Corresponds to GO TO line 630 in the original Fortran code."""
        if self.BIS[[i]] > 0.11:
            self.doLine640(i)
        else:
            self.IDVP += 1
            self.IBI[[i]] = 1
            self.doLine690(i)
    
    def doLine632(self, i):
        """Corresponds to GO TO line 632 in the original Fortran code."""
        self.BIS[[i]] = 0.0
        self.PBIS[[i]] = 0.0
        self.T[[i]] = 0.0
        self.doLine630(i)        
    
    def doLine640(self, i):
        """Corresponds to GO TO line 640 in the original Fortran code."""
        if self.BIS[[i]] <= 0.31:
            self.IDP += 1
            self.IBI[[i]] = 2
        elif self.BIS[[i]] <= 0.51:
            self.IDG += 1
            self.IBI[[i]] = 3
        elif self.BIS[[i]] <= 0.71:
            self.IDVG += 1
            self.IBI[[i]] = 4
        elif self.BIS[[i]] <= 0.91:
            self.IDVVG += 1
            self.IBI[[i]] = 5
        else:
            self.IDEX += 1
            self.IBI[[i]] = 5
        self.doLine690(i)
        
    def doLine690(self, i):
        """Corresponds to GO TO line 690 in the original Fortran code."""
        self.SDI += self.DIFI[[i]]
        self.SBIS += self.BIS[[i]]
    
    def processTestResults(self):
        for i in range(1, self.ITEMN + 1):
            for j in range(1, self.JCHO + 1):
                self.KTOT.addValueAtIndex([i], self.JTOT[[i, j]])
                self.TOT[[i, j]] = self.JTOT[[i, j]]
                self.FKSUM[[i, j]] = float(self.KSUM[[i, j]])
                self.CMEAN[[i, j]] = 0.0 if (self.TOT[[i, j]] <= 0) else (float(self.FKSUM[[i, j]]) / float(self.TOT[[i, j]]))
                self.PROP[[i, j]] = float(self.TOT[[i, j]]) / float(self.FITN)
            self.FCOUNT[[i]] = float(self.ICOUNT[[i]])
            self.DIFI[[i]] = self.FCOUNT[[i]] / float(self.FITN)
            if self.DIFI[[i]] <= 0.19:
                self.IDO += 1
            elif self.DIFI[[i]] <= 0.39:
                self.IDTW += 1
            elif self.DIFI[[i]] <= 0.59:
                self.IDTH += 1
            elif self.DIFI[[i]] <= 0.79:
                self.IDFO += 1
            elif self.DIFI[[i]] <= 1.0:
                self.IDFI += 1
            else:
                # '0DIFFICULTY OF ITEM', I2,'  IS GREATER THAN ONE OR LESS THAN ZERO.'
                #outputFPtr.write('0DIFFICULTY OF ITEM{:2d}  IS GREATER THAN ONE OR LESS THAN ZERO.'.format(i))
                self._messages.append('0DIFFICULTY OF ITEM{:2d}  IS GREATER THAN ONE OR LESS THAN ZERO.'.format(i))
                
        if self.KODE < 1:
            for i in range(1, self.ITEMN + 1):
                if self.DIFI[[i]] > 0.40 and self.DIFI[[i]] <= 0.61:
                    self.IDI[[i]] = 5
                elif self.DIFI[[i]] > 0.30 and self.DIFI[[i]] <= 0.71:
                    self.IDI[[i]] = 4
                elif self.DIFI[[i]] > 0.20 and self.DIFI[[i]] <= 0.81:
                    self.IDI[[i]] = 3
                elif self.DIFI[[i]] > 0.10 and self.DIFI[[i]] <= 0.91:
                    self.IDI[[i]] = 2
                else:
                    self.IDI[[i]] = 1
        
        self.FSUM = float(self.ISUM)
        self.FSUMSQ = float(self.ISUMSQ)
        self.FMEAN = self.FSUM / self.FITN
        self.FVAR = (self.FITN * self.FSUMSQ - self.FSUM**2) / (self.FITN * (self.FITN - 1.0))
        self.SER = 1.0 / math.sqrt(self.FITN - 1.0)
        self.SDEV = math.sqrt(self.FVAR)
        
        for i in range(1, self.ITEMN + 1):
            for j in range(1, self.JCHO + 1):
                self.IDIST[[i, j]] = 2 if self.PROP[[i, j]] < self.CHEK[self.ICHO] else 1
            k = self.KORAN[i - 1] + 1
            self.IDIST[[i, k]] = 2 if (self.PROP[[i, k]] < 0.2 or self.PROP[[i, k]] > 0.8) else 1
            for j in range(1, self.JCHO + 1):
                if self.IDIST[[i, j]] != 2:
                    if self.CMEAN[[i, j]] > self.CMEAN[[i, k]] or self.CMEAN[[i, k]] < self.FMEAN:
                        self.IDIST[[i, j]] = 2
        
        for i in range(1, self.ITEMN + 1):
            if self.DIFI[[i]] < 0.0:
                self.doLine570(i)
            elif isclose(self.DIFI[[i]], 0.0):
                self.FMNCO[[i]] = 0.0
                self.FMNIC[[i]] = self.FMEAN
                self.doLine570(i)
            elif isclose(self.DIFI[[i]], 1.0):
                self.FMNCO[[i]] = self.FMEAN
                self.FMNIC[[i]] = 0.0
                self.doLine570(i)
            else:
                if self.DIFI[[i]] < 0.5:
                    if self.DIFI[[i]] <= 0:
                        self.doLine620(i)
                    else:
                        self.doLine610(i, 1.0 - self.DIFI[[i]])
                elif self.DIFI[[i]] > 0.5:
                    if self.DIFI[[i]] > 1.0:
                        self.doLine620(i)
                    else:
                        self.doLine610(i, self.DIFI[[i]])
                else:
                    self.Y[[i]] = 0.39894
                    self.doLine620(i)

    def calculateAggregateStats(self):
        self.FMEDI = self.SDI / self.GITEMN
        self.FMEBIS = self.SBIS / self.GITEMN
        self.CORI = self.FMEBIS**2
        if isclose(self.FVAR, 0.0):
            self.REL = 0.0
            self.SEMEAS = 0.0
        else:
            self.REL = (self.GITEMN / (self.GITEMN - 1.0)) * ((self.FVAR - self.VAR) / self.FVAR)
            self.SEMEAS = self.SDEV * math.sqrt(1.0 - self.REL)
        for KEY in range(1, self.KCHO + 1):
            self.PCTKEY[[KEY]] = self.CNTKEY[[KEY]] / self.GITEMN
            self.PCTCHO[[KEY]] = self.CNTCHO[[KEY]] / (self.FITN * self.GITEMN)
            if isclose(self.CNTKEY[[KEY]], 0.0):
                self.AVDIFF[[KEY]] = 0.0
            else:
                self.AVDIFF[[KEY]] = self.PROSUM[[KEY]] / self.CNTKEY[[KEY]]
        self.ITITEM = int(self.GITEMN)
        if self.MCOPY > 1:
            self.NCOPY = 3
        if self.NCOPY == 0:
            self.NCOPY = 1

#
# Configure the command line argument parser:
#
cliParser = argparse.ArgumentParser(description='Statistical analyses of multiple-choice responses.')
cliParser.add_argument('--input', '-i',
        dest='inputFiles',
        action='append',
        metavar='<file|->',
        help='an input file to be processed; may be used multiple times, "-" implies standard input and may be used only once (and is the default if no input files are provided)'
    )
cliParser.add_argument('--output', '-o',
        dest='outputFiles',
        action='append',
        metavar='<file|->',
        help='an output file to write data to; may be used multiple times, "-" implies standard output (and is the default if no input files are provided)  NOTE:  if the number of output files is fewer than the number of input files, the final output file will have multiple analyses written to it'
    )
cliParser.add_argument('--append', '-a',
        dest='should_append',
        action='store_true',
        default=False,
        help='always append to output files'
    )
cliParser.add_argument('--format', '-f',
        dest='fileFormat',
        default='fortran',
        help='file format to read and write: ' + ', '.join(formatsRecognized.keys())
    )

# Parse the command line arguments:
cliArgs = cliParser.parse_args()

# If no input files were specified, ensure a read from stdin:
if cliArgs.inputFiles is None or len(cliArgs.inputFiles) == 0:
    cliArgs.inputFiles = ['-']
    
# If no output files were specified, ensure a write to stdout:
if cliArgs.outputFiles is None or len(cliArgs.outputFiles) == 0:
    cliArgs.outputFiles = ['-']

# Ensure only one stdin is present in input file list:
if len([v for v in cliArgs.inputFiles if v == '-']) > 1:
    sys.stderr.write('ERROR:  stdin ("-") cannot be used multiple times with --input/-i\n')
    sys.exit(errno.EINVAL)

# Validate the file format:
fileFormat = cliArgs.fileFormat.lower()
if fileFormat not in formatsRecognized:
    sys.stderr.write('ERROR:  file format "{:s}" is not available'.format(cliArgs.fileFormat))
    sys.exit(errno.EINVAL)

# Starting from empty input and output streams:
inputFPtr = False
outputFPtr = False

# As long as we have input files to read, keep looping:
while len(cliArgs.inputFiles) > 0:
    # Is there another input file in that list?
    if len(cliArgs.inputFiles) > 0:
        # Close previous input file (so long as it wasn't stdin):
        if inputFPtr and inputFile != '-':
            inputFPtr.close()
        # Pull the next input file out of the list:
        inputFile = cliArgs.inputFiles.pop(0)
        
        # Attempt to open the input file:
        if inputFile == '-':
            inputFPtr = sys.stdin
        else:
            try:
                inputFPtr = open(inputFile, 'r')
            except IOError as E:
                if E.errno == errno.ENOENT:
                    sys.stderr.write('ERROR:  input file "{:s}" does not exist\n'.format(inputFile))
                elif E.errno == errno.EACCES:
                    sys.stderr.write('ERROR:  unable to open input file "{:s}":  {:s}\n'.format(inputFile, str(E)))
                else:
                    sys.stderr.write('ERROR:  error opening input file "{:s}":  {:s}\n'.format(inputFile, str(E)))
                sys.exit(E.errno)
    
    # Is there another output file in that list?
    if len(cliArgs.outputFiles) > 0:
        # Close previous output file (so long as it wasn't stdout):
        if outputFPtr and outputFile != '-':
            outputFPtr.close()
        # Pull the next output file out of the list:
        outputFile = cliArgs.outputFiles.pop(0)
        
        # Attempt to open the output file:
        if outputFile == '-':
            outputFPtr = sys.stdout
        else:
            try:
                outputFPtr = open(outputFile, 'a' if cliArgs.should_append else 'w')
            except Exception as E:
                sys.stderr.write('ERROR:  failed to open output file "{:s}":  {:s}\n'.format(outputFile, str(E)))
                sys.exit(errno.EIO)
    
    try:
        # With input and output streams open, process the results in the input file.  First, create an empty
        # StatData object to hold the analysis and parameters:
        stats = StatData()
    
        # Create an i/o helper associated with that StatData object:
        helper = (formatsRecognized[fileFormat])(stats)
    
        # Can we read an initial header from that file?
        if helper.readHeader(inputFPtr, False):
            # Excellent, we got a header; go ahead and summarize it and then fixup the answer indices
            # if necessary ((E=1, D=2, ...) vs. (A=1, B=2, ...)):
            helper.summarizeControlCard(outputFPtr)
            helper.fixupAnswerKey()
        
            # Prepare for reading student data -- basically this is allocating all per-test section arrays
            # and variables:
            stats.prepForDataRead()
        
            # Attempt to read the student answer data from the input file:
            studentData = helper.readStudentData(inputFPtr, outputFPtr)
        
            # Now do all the statistics for those test results:
            helper.processTestResults(outputFPtr)
        
            # Print the summary of the answers (and possibly the overall summary for the entire test);
            # this subroutine will return True if there are more test sections in the input file:
            while helper.printResults(inputFPtr, outputFPtr, studentData):
                # Did we find an additional test section?
                if helper.readHeader(inputFPtr, True):
                    # Excellent, we got a header; go ahead and summarize it and then fixup the answer indices
                    # if necessary ((E=1, D=2, ...) vs. (A=1, B=2, ...)):
                    helper.summarizeControlCard(outputFPtr)
                    helper.fixupAnswerKey()
        
                    # Prepare for reading student data -- basically this is allocating all per-test section arrays
                    # and variables:
                    stats.prepForDataRead()
                
                    # Attempt to read the student answer data from the input file:
                    studentData = helper.readStudentData(inputFPtr, outputFPtr)

                    # Now do all the statistics for those test results:
                    helper.processTestResults(outputFPtr)
                else:
                    break
                    
    except Exception as E:
        print('ERROR:  ' + str(E))
        sys.exit(1)
    