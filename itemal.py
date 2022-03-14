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
import os
import errno
import re
import datetime
import functools
import argparse
import math

##
####
##

#
# File formats recognized by the program:
#
inputFormatsRecognized = {
        'fortran':      lambda:FortranIO(),
        'json':         lambda:JSONIO(),
        'json+pretty':  lambda:JSONIO(shouldPrintPretty=True)
    }
outputFormatsRecognized = {
        'fortran':      lambda:FortranIO(),
        'json':         lambda:JSONIO(),
        'json+pretty':  lambda:JSONIO(shouldPrintPretty=True)
    }

##
####
##

try:
    import dateparser
    
    def genericDateParse(dateString):
        """Wrapper around the dateparser.parse() function if that module is present in this Python instance."""
        return dateparser.parse(dateString)
except:
    def genericDateParse(dateString):
        """Attempt to parse a date given a set of expected formats for strptime().  Used if the dateparser module is not present in this Python instance."""
        for dateFormat in [ '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%m%d%y', '%x' ]:
            try:
                return datetime.datetime.strptime(dateString, dateFormat)
            except:
                pass
        raise ValueError('Unable to parse "{:s}" with any known date-time format.'.format(dateString))

##
####
##

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
        """Determine if a is within the given tolerance of b."""
        return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

##
####
##

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

##
####
##

class ITEMALData(object):
    """This is an abstract base class for the ITEMAL in-memory data representation class hierarchy."""
    
    def exportAsDict(self):
        """Package the object as a dictionary."""
        return {}

##
####
##

class Options(ITEMALData):
    """An Options object (possibly) holds values for the optional attributes that can be associated with an Exam or ExamSection."""
    
    def exportAsDict(self):
        """Add an 'options' key to the base export dictionary with any option attributes for the receiver."""
        d = super(Options, self).exportAsDict()
        d.update(self._values)
        return d
    
    #
    # To add new attributes, simply augment this dictionary with the key and default value:
    #
    defaultValues = {
        'is-order-reversed': False,
        'number-of-copies': 1,
        'should-eval-full-exam-only': False
    }

    def __init__(self, fromDict=None):
        self._values = {}
        if fromDict is not None:
            src = fromDict._values if isinstance(fromDict, Options) else fromDict
            for k in self.defaultValues:
                if k in src:
                    self._values[k] = src[k]
        
    def __repr__(self):
        outStr = 'Options('
        appended = False
        for k in self.defaultValues:
            if k in self._values:
                outStr += ('{' if not appended else ',') + "'" + k + "':" + repr(self._values[k])
                appended = True
        return outStr + ('})' if appended else ')')

    #
    # Sequence magic methods are defined for read access to string-keyed option values:
    #
    def __iter__(self):
        return self.defaultValues.__iter__()
    def __len__(self):
        return len(self.defaultValues)
    def __getitem__(self, key):
        return self._values.get(key, self.defaultValues[key])
    
    def mergeWithOptions(self, otherOptions):
        """Any attributes with an assigned value in otherOptions are set to those values in the receiver."""
        self._values.update(otherOptions._values)
    
    def mergeWithOptionsDict(self, optionsDict):
        """Any attributes with a value in optionsDict are set to those values in the receiver."""
        self._values.update(optionsDict)

##
####
##

class StudentAnswers(ITEMALData):
    """A StudentAnswers object holds the answer key, per-student scores, and per-student answer list.  Each ExamSection will have zero or more instances of this class -- one for each group of students.
    
Scores can be provided on initialization from the dictionary, but can also be calculated if supplied with the answer key for the questions."""
    
    def exportAsDict(self):
        """Add the receiver's fields to the export dict."""
        d = super(StudentAnswers, self).exportAsDict()
        d.update({
                'scores': self.scores(),
                'answers': self.answers(),
                'group-id': self.groupId(),
            })
        return d
    
    lastGroupId = 0
    
    @classmethod
    def nextGroupId(cls):
        cls.lastGroupId += 1
        return str(cls.lastGroupId)
    
    def __init__(self, fromDict=None):
        self._scores = []
        self._answers = []
        if fromDict is not None:
            self._groupId = str(fromDict['group-id']) if ('group-id' in fromDict) else StudentAnswers.nextGroupId()
            
            if 'scores' in fromDict:
                self._scores = [int(s) for s in fromDict['scores']]
            if 'answers' in fromDict:
                firstAnswers = None
                for answers in fromDict['answers']:
                    theseAnswers = [int(a) for a in answers]
                    if firstAnswers is None:
                        firstAnswers = theseAnswers
                    elif len(theseAnswers) != len(firstAnswers):
                        raise ValueError('Answer set of dimension {:d} does not match first answers dimension {:d} for group {:s}.'.format(len(theseAnswers), len(firstAnswers), self._groupId))
                    self._answers.append(theseAnswers)
        else:
            self._groupId = StudentAnswers.nextGroupId()
    
    def groupId(self):
        return self._groupId
    def setGroupId(self, groupId):
        self._groupId = str(groupId)
    
    def scores(self):
        return self._scores
    
    def answers(self):
        return self._answers
        
    def maxResponseCount(self):
        return max([max([a for a in A]) for A in self._answers])
    
    def answerCount(self):
        return len(self._answers[0]) if (len(self._answers) > 0) else 0
    
    def studentCount(self):
        return len(self._answers)
    
    def reset(self, groupId=None):
        self._scores = []
        self._answers = []
    
    def appendStudentData(self, score, answers):
        if len(self._answers) > 0 and len(answers) != len(self._answers[0]):
            raise ValueError('Attempt to append student answers of mismatched dimension ({:d} vs {:d}).'.format(len(answers), len(self._answers)))
        self._answers.append([int(a) for a in answers])
        self._scores.append(int(score))
    
    def calculateScoresForAnswerKey(self, answerKey):
        if len(self._answers) > 0:
            if len(answerKey) != len(self._answers[0]):
                raise ValueError('Attempt to calculation scores from answer key of invalid dimension {:d}.'.format(len(answerKey)))
            self._scores = [
                                functools.reduce(lambda a, b: a + b, [0 if (a != b) else 1 for (a, b) in zip(A, answerKey)])
                                for A in self._answers
                            ]
                            
    def reverseAnswerOrdering(self, responsesPerAnswer):
        if len(self._answers) > 0:
            self._answers = [((responsesPerAnswer + 1 - i) if i else 0) for i in self._answers]
            

##
####
##            

class ExamSection(ITEMALData):
    
    def exportAsDict(self):
        """Add the receiver's fields to the export dict."""
        d = super(ExamSection, self).exportAsDict()
        d.update({
                'responses-per-question': self.responsesPerQuestion(),
                'options': self.options().exportAsDict(),
                'answer-key': self.answerKey(),
                'responses': [A.exportAsDict() for A in self.studentAnswersGroups()]
            })
        statsData = self.statisticalSummary()
        if statsData is not None:
            d['statistics'] = statsData
        return d

    def __init__(self, fromDict=None, parentOptions=None):
        self._responsesPerQuestion = 0
        self._answerKey = []
        self._studentAnswersGroups = []
        self._options = Options(parentOptions)
        self._fortranFormatString = None
        self._fortranNewPageBadges = []
        self._statisticalSummary = None
        if fromDict is not None:
            if 'responses-per-question' in fromDict:
                self.setResponsesPerQuestion(int(fromDict['responses-per-question']))
            
            if 'options' in fromDict:
                self._options.mergeWithOptionsDict(fromDict['options'])
                
            if 'answer-key' in fromDict:
                self.setAnswerKey(fromDict['answer-key'])
                
            if 'responses' in fromDict:
                firstAnswers = None
                for fromDict in fromDict['responses']:
                    self.addStudentAnswers(StudentAnswers(fromDict=fromDict))
        else:
            self._options = Options()
    
    #
    # Sequence magic methods are defined for read access to answers groups list:
    #
    def __len__(self):
        return len(self._studentAnswersGroups)
    def __getitem__(self, key):
        if isinstance(key, (str, unicode)):
            return self.studentAnswersForGroupId(key)
        return self._studentAnswersGroups[key]
    
    def options(self):
        return self._options
    def setOptions(self, options):
        self._options = Options(options)
        
    def responsesPerQuestion(self):
        return self._responsesPerQuestion
    def setResponsesPerQuestion(self, responsesPerQuestion):
        if len(self._answerKey) > 0:
            if max(self._answerKey) > responsesPerQuestion:
                raise ValueError('Attempt to set responsesPerQuestion={:d} which is < maximum response in the answer key {:d}.'.format(responsesPerQuestion, max(self._answerKey)))
        self._responsesPerQuestion = responsesPerQuestion
    
    def answerKey(self):
        return self._answerKey
    def questionCount(self):
        return len(self._answerKey)
    def setAnswerKey(self, answerKey):
        if len(answerKey) > 0:
            if len(self._studentAnswersGroups) > 0:
                firstAnswers = self._studentAnswersGroups[0]
                if len(answerKey) != firstAnswers.answerCount():
                    raise ValueError('Answer key answer count {:d} differs from group {:s} count {:d}.'.format(theseAnswers.groupId(), firstAnswers.groupId()))
            answerKey = [int(a) for a in answerKey]
            if self._responsesPerQuestion == 0:
                self._responsesPerQuestion = max(answerKey)
            elif self._responsesPerQuestion > 0 and max(answerKey) > self._responsesPerQuestion:
                raise ValueError('Items in answer key {:s} exceed configured maximum response count {:d}.'.format(''.join(answerKey), self._responsesPerQuestion))
        self._answerKey = answerKey
        self._fortranNewPageBadges = [False]*len(answerKey)
    
    def studentCount(self):
        return [g.studentCount() for g in self._studentAnswersGroups]
        
    def totalStudentCount(self):
        return functools.reduce(lambda a, b: a + b, self.studentCount())
    
    def studentAnswersGroups(self):
        return self._studentAnswersGroups
    def studentAnswersGroupsCount(self):
        return len(self._studentAnswersGroups)
    def studentAnswersGroupAtIndex(self, groupIndex):
        return self._studentAnswersGroups[groupIndex]
    def studentAnswersGroupIds(self):
        return [g.groupId() for g in self._studentAnswersGroups]
    def studentAnswersForGroupId(self, groupId):
        ids = self.studentAnswersGroupIds()
        return self._studentAnswersGroups[ids.index(groupId)] if (groupId in ids) else None
    def setStudentAnswersGroups(self, studentAnswersGroups):
        self._studentAnswersGroups = []
        for studentAnswers in studentAnswersGroups:
            self.addStudentAnswers(studentAnswers)
    def addStudentAnswers(self, studentAnswers):
        if studentAnswers.groupId() in self._studentAnswersGroups:
            raise KeyError('Group {:s} already exists in exam section.'.format(studentAnswers.groupId()))
        if studentAnswers.answerCount() > 0:
            # Does this incoming answers' dimension(s) match the extant answers groups?
            if len(self._studentAnswersGroups) > 0:
                # We'll examine the first element that's already been validated:
                otherAnswers = self._studentAnswersGroups[0]
                # Matching number of answers in both?
                if studentAnswers.answerCount() != otherAnswers.answerCount():
                    raise ValueError('Attempt to add answer group with dimension {:d} to exam with existing groups of dimension {:d}.'.format(studentAnswers.answerCount(), otherAnswers.answerCount()))
            # If a maximum number of responses per question is set, then we'll need to verify the
            # new group of answers doesn't have any answer that exceeds that limit.  But if our
            # maximum is not yet set, we need to set it now to reflect the max of the new set:
            if self._responsesPerQuestion == 0:
                self._responsesPerQuestion = studentAnswers.maxResponseCount()
            elif self._responsesPerQuestion < studentAnswers.maxResponseCount():
                raise ValueError('Attempt to add answer group with maximum response count {:d} that exceeds exam section count {:d}.'.format(studentAnswers.maxResponseCount(), self._responsesPerQuestion))
        self._studentAnswersGroups.append(studentAnswers)
    
    def fortranFormatString(self):
        return self._fortranFormatString
    def setFortranFormatString(self, formatString):
        self._fortranFormatString = formatString
    
    def fortranNewPageBadges(self):
        return self._fortranNewPageBadges
    def setFortranNewPageBadge(self, questionIndex, newPageState=True):
        self._fortranNewPageBadges[questionIndex] = newPageState
        
    def statisticalSummary(self):
        return self._statisticalSummary
    def setStatisticalSummary(self, statisticalSummary):
        self._statisticalSummary = statisticalSummary

    def reverseAnswerOrderingIfNecessary(self):
        if self.options()['is-order-reversed']:
            responsesPerQuestion = self.responsesPerQuestion()
            if responsesPerQuestion <= 0:
                raise RuntimeError('Unable to reorder answer indices since maximum response index per question is {:d}.'.format(responsesPerQuestion))
            if len(self._answerKey) > 0:        
                self.setAnswerKey([(responsesPerQuestion + 1 - i) for i in responsesPerQuestion])
            for studentAnswerGroup in self.studentAnswerGroups():
                studentAnswerGroup.reverseAnswerOrdering(responsesPerQuestion)

    def calculateScoresFromAnswerKey(self):
        if len(self._answerKey) == 0:
            raise RuntimeError('Exam section lacks an answer key from which to calculate student scores.')
        for studentAnswers in self._studentAnswersGroups:
            studentAnswers.calculateScoresForAnswerKey(self._answerKey)

##
####
##

class Exam(ITEMALData):
        
    answerSymbolByIndex = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    
    def exportAsDict(self):
        """Add the receiver's fields to the export dict."""
        d = super(Exam, self).exportAsDict()
        d.update({
                'exam-id': self.examId(),
                'course-name': self.courseName(),
                'instructor': self.instructor(),
                'options': self.options().exportAsDict(),
                'exam-date': self.examDate(),
                'exam-sections': [S.exportAsDict() for S in self.examSections()]
            })
        statsData = self.statisticalSummary()
        if statsData is not None:
            d['statistics'] = statsData
        return d
    
    lastExamId = 0
    
    @classmethod
    def nextExamId(cls):
        cls.lastExamId += 1
        return str(cls.lastExamId)

    def __init__(self, fromDict=None):
        self._courseName = ''
        self._instructor = ''
        self._examDate = datetime.datetime.fromtimestamp(0)
        self._examSections = []
        self._statisticalSummary = None
        self._options = Options()
        if fromDict is not None:
            self._examId = fromDict['exam-id'] if ('exam-id' in fromDict) else Exam.nextExamId()
            self._courseName = fromDict.get('course-name', self._courseName)
            self._instructor = fromDict.get('instructor', self._instructor)
            
            if 'options' in fromDict:
                self._options.mergeWithOptionsDict(fromDict['options'])
            
            if 'exam-date' in fromDict:
                self._examDate = genericDateParse(fromDict['exam-date'])
            
            if 'exam-sections' in fromDict:
                for sectionDict in fromDict['exam-sections']:
                    self.addExamSection(ExamSection(fromDict=sectionDict, parentOptions=self._options))
                    
        else:
            self._examId = Exam.nextExamId()
    
    #
    # Sequence magic methods are defined for read access to examSections list:
    #
    def __len__(self):
        return len(self._examSections)
    def __getitem__(self, key):
        return self._examSections[key]
    
    def examId(self):
        return self._examId
    def setExamId(self, examId):
        self._examId = str(examId)
    
    def courseName(self):
        return self._courseName
    def setCourseName(self, courseName):
        self._courseName = str(courseName)
    
    def instructor(self):
        return self._instructor
    def setInstructor(self, instructor):
        self._instructor = str(instructor)
    
    def examDate(self):
        return self._examDate
    def setExamDate(self, examDate):
        self._examDate = examDate
    
    def totalQuestionCount(self):
        return functools.reduce(lambda a, b: a + b.questionCount(), self._examSections, 0)
    
    def examSections(self):
        return self._examSections
    def examSectionCount(self):
        return len(self._examSections)
    def examSectionAtIndex(self, sectionIndex):
        return self._examSections[sectionIndex]
    def setExamSections(self, examSections):
        self._examSections = []
        for examSection in examSections:
            self.addExamSection(examSection)
    def addExamSection(self, examSection):
        if len(self._examSections) > 0:
            # Student counts (in a by-group list) must be the same across exam sections:
            if examSection.studentCount() != self._examSections[0].studentCount():
                raise ValueError('Attempt to add exam section with {:s} students to exam with existing sections containing {:s} students.'.format(str(examSection.studentCount()), str(self._examSections[0].studentCount())))
            # Groups should have the same ids:
            if len(set(examSection.studentAnswersGroupIds()).symmetric_difference(self._examSections[0].studentAnswersGroupIds())) > 0:
                raise ValueError('Attempt to add exam section with different group ids than existing sections.')
        # Hand our options to the new exam section:
        examSection.options().mergeWithOptions(self._options)
        self._examSections.append(examSection)
        
    def statisticalSummary(self):
        return self._statisticalSummary
    def setStatisticalSummary(self, statisticalSummary):
        self._statisticalSummary = statisticalSummary
    
    def options(self):
        return self._options
    def setOptions(self, options):
        self._options = Options(options)
        for examSection in self._examSections:
            examSection.options().mergeWithOptions(self._options)

    def calculateScoresFromAnswerKeys(self):
        for examSection in self._examSections:
            examSection.calculateScoresFromAnswerKey()
            
    def totalStudentCount(self):
        return self._examSections[0].totalStudentCount() if (len(self._examSections) > 0) else None
        
    def reverseAnswerOrderingIfNecessary(self):
        for examSection in self._examSections:
            examSection.reverseAnswerOrderingIfNecessary()

##
####
##

class StatData(object):
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
    
    def processExamSection(self, exam, examSection):
        """Initialize statistical data object fields that get reset before student data are processed."""
        # Stuff from the Fortran header:
        self.KODE = 0 if exam.options()['should-eval-full-exam-only'] else 1
        self.ICHO = examSection.responsesPerQuestion()
        self.IDIG = 2 if examSection.options()['is-order-reversed'] else 1
        self.NCOPY = examSection.options()['number-of-copies']
        
        self.ITN = examSection.totalStudentCount()
        self.FITN = float(self.ITN)
        
        self.ITEMN = examSection.questionCount()
        self.FITEMN = float(self.ITEMN)
        self.GITEMN = self.GITEMN + self.FITEMN
        
        # Initialize the rest of the per-section variables:
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
        
        # Tally all student answers in the section:
        answerKey = examSection.answerKey()
        l = 0
        while l < examSection.studentAnswersGroupsCount():
            answerGroup = examSection.studentAnswersGroupAtIndex(l)
            l += 1
            
            scores = answerGroup.scores()
            answers = answerGroup.answers()
            
            self.KOUNT[[l]] += answerGroup.studentCount()
            self.ISUM += functools.reduce(lambda a, b: a + b, scores, 0)
            self.ISUMSQ += functools.reduce(lambda a, b: a + b**2, scores, 0)
            
            a = 0
            while a < len(answers):
                studentAnswers = answers[a]
                score = scores[a]
                a += 1
                i = 0
                while i < len(answerKey):
                    if answerKey[i] == studentAnswers[i]:
                        self.ICOUNT[[i + 1]] += 1
                        self.ITC[[i + 1]] += score
                    else:
                        self.ITIC[[i + 1]] += score
                    if studentAnswers[i] < 0:
                        #   270 FORMAT (1H0,24HA RESPONSE FOR QUESTION ,I2,1X,10HFOR GROUP ,I1,1X,
                        #      116HREAD AS NEGATIVE)
                        self._messages.append('A RESPONSE FOR QUESTION {:2d} FOR GROUP {:1d} READ AS NEGATIVE'.format(i + 1, l))
                        continue
                    elif studentAnswers[i] > self.ICHO:
                        #   290 FORMAT (1H0,24HA RESPONSE FOR QUESTION ,I2,1X,10HFOR GROUP ,I1,1X,
                        #      121HREAD AS GREATER THAN ,I1)
                        self._messages.append('A RESPONSE FOR QUESTION {:2d} FOR GROUP {:1d} READ AS GREATER THAN {:1d}'.format(i + 1, l, self.ICHO))
                        continue
                    else:
                        j = studentAnswers[i] + 1
                        self.ITAB[[i + 1, j, l]] += 1
                        self.JTOT[[i + 1, j]] += 1
                        self.KSUM[[i + 1, j]] += score
                    i += 1
                
        # Calculate statistical summary for the section:
        for i in range(1, self.ITEMN + 1):
            for j in range(1, self.JCHO + 1):
                self.KTOT[[i]] += self.JTOT[[i, j]]
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
            k = answerKey[i - 1] + 1
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
    
        self.NNXYZ += self.ITEMN
        for i in range(1, self.ITEMN + 1):
            KEY = answerKey[i - 1]
            self.CNTKEY[[KEY]] += 1.0
            self.PROSUM[[KEY]] += self.PROP[[i, KEY + 1]]
            for j in range(2, self.JCHO + 1):
                self.CNTCHO[[j - 1]] += self.TOT[[i, j]]
        self.KTN = self.ITN
        self.KCHO = self.ICHO
        self.MCOPY = examSection.options()['number-of-copies']
        
        # What do we cram back into the exam section as results?
        L1 = 0
        L2 = 1
        JUP = self.NNXYZ
        questionSummaries = []
        for i in range(1, self.ITEMN + 1):
            JUP += 1
            KAN = answerKey[i - 1]
            KOR = KAN + 1
            if self.IDIG == 2:
                KAN = self.JCHO - KAN
            L1 += 1
            L2 += 1
            shouldInsertNewPage = False
            if i <= 2:
                shouldInsertNewPage = False
            elif self.ICHO <= 5:
                if L2 <= 3:
                    shouldInsertNewPage = False
                else:
                    shouldInsertNewPage = True
                    L1 = 1
                    L2 = 1
            elif L1 > 2:
                shouldInsertNewPage = True
                L1 = 1
                L2 = 1
            else:
                shouldInsertNewPage = False
        
            j = 1
            perQuestionSummary = {
                    'should-insert-new-page': shouldInsertNewPage,
                    'omitted': {
                            'is-correct-answer': (KOR == j),
                            'index': 0,
                            'count-by-group': [self.ITAB[[i, j, L]] for L in range(1, examSection.studentAnswersGroupsCount() + 1)],
                            'total-responses': self.JTOT[[i, j]],
                            'chosen-by-ratio': self.PROP[[i, j]],
                            'mean-score': self.CMEAN[[i, j]],
                            'is-questionable': False
                        },
                    'total': {
                            'count-by-group': [self.KOUNT[[L]] for L in range(1, examSection.studentAnswersGroupsCount() + 1)],
                            'total-responses': self.KTOT[[i]]
                        },
                    'by-answer': {},
                    'biserial-correlation': self.BIS[[i]],
                    'pointwise-biserial-correlation': self.PBIS[[i]],
                    't-value': self.T[[i]]
                }
            JK = self.JCHO
            for j in range(2, self.JCHO + 1):
                if self.IDIG == 2:
                    JK -= 1
                    K = JK
                else:
                    K = j - 1
                IDIS = self.IDIST[[i, j]]
                perQuestionSummary['by-answer'][Exam.answerSymbolByIndex[j - 1]] = {
                        'is-correct-answer': (KOR == j),
                        'index': K,
                        'count-by-group': [self.ITAB[[i, j, L]] for L in range(1, examSection.studentAnswersGroupsCount() + 1)],
                        'total-responses': self.JTOT[[i, j]],
                        'chosen-by-ratio': self.PROP[[i, j]],
                        'mean-score': self.CMEAN[[i, j]],
                        'is-questionable': True if (IDIS == 2) else False
                    }
            questionSummaries.append(perQuestionSummary)
        
        # Attach the summaries to the exam section:
        examSection.setStatisticalSummary(questionSummaries)
        
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
    
    def processExam(self, exam):
        # Do the exam sections first:
        for examSection in exam.examSections():
            self.processExamSection(exam, examSection)
        
        # Do the full-stats:
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
        
        examSummary = {
                'mean-difficulty': self.FMEDI,
                'total-biserial-correlation': self.FMEBIS,
                'kuder-richardson-20-reliability': self.REL,
                'score-mean': self.FMEAN,
                'score-variance': self.FVAR,
                'score-std-deviation': self.SDEV,
                'std-error-of-measurement-kr-20': self.SEMEAS,
                'total-students': self.KTN,
                'total-questions': self.ITITEM,
                'distribution-by-passing': [
                        { 'range': [0, 19], 'item-count': self.IDO },
                        { 'range': [20, 39], 'item-count': self.IDTW },
                        { 'range': [40, 59], 'item-count': self.IDTH },
                        { 'range': [60, 79], 'item-count': self.IDFO },
                        { 'range': [80, 100], 'item-count': self.IDFI }
                    ],
                'distribution-by-biserial-correlation': [
                        { 'range': [None, 0.10], 'item-count': self.IDVP },
                        { 'range': [0.11, 0.30], 'item-count': self.IDP },
                        { 'range': [0.31, 0.50], 'item-count': self.IDG },
                        { 'range': [0.51, 0.70], 'item-count': self.IDVG },
                        { 'range': [0.71, 0.90], 'item-count': self.IDVVG },
                        { 'range': [0.91, None], 'item-count': self.IDEX }
                    ],
                'breakdown-by-choice':
                        { Exam.answerSymbolByIndex[k]: {
                                        'pct-keyed': self.PCTKEY[[k]],
                                        'pct-chosen': self.PCTCHO[[k]],
                                        'avg-difficulty': self.AVDIFF[[k]]
                                    }
                                for k in range(1,self.PCTKEY.maxDimension()[0])
                            }
            }
        exam.setStatisticalSummary(examSummary)
        
        # Fixup number of copies for the sake of form-based outputs:
        if self.MCOPY > 1:
            exam.options().mergeWithOptionsDict({ 'number-of-copies': 3 })
        if exam.options()['number-of-copies'] == 0:
            exam.options().mergeWithOptionsDict({ 'number-of-copies': 1 })
    
    def messages(self):
        """Return all accumulated messages and reset the message list to empty."""
        return self._messages
    def clearMessages(self):
        self._messages = []

##
####
##

class BaseIO(object):

    def readExamData(self, inputFPtr):
        """Concrete subclasses should override this method."""
        raise NotImplementedError('No readExamData() method implemented for the {:s} class.'.format(self.__class__.__name__))
    
    def writeExamDataAndSummaries(self, outputFPtr, examData):
        """Concrete subclasses should override this method."""
        raise NotImplementedError('No writeExamDataAndSummaries() method implemented for the {:s} class.'.format(self.__class__.__name__))


##
####
##

import json

class JSONIO(BaseIO):

    def __init__(self, shouldPrintPretty = False):
        super(JSONIO, self).__init__()
        self._prettyPrint = shouldPrintPretty

    def readExamData(self, inputFPtr):
        return json.load(inputFPtr)
    
    def writeExamDataAndSummaries(self, outputFPtr, examData):
        document = examData.exportAsDict()
        if 'exam-date' in document:
            document['exam-date'] = datetime.datetime.strftime(document['exam-date'], '%Y-%m-%d')
        if self._prettyPrint:
            json.dump(document, outputFPtr, indent=4)
        else:
            json.dump(document, outputFPtr)

##
###
##

try:
    #
    # Attempt to load the PyYAML library into this namespace.  If successful, then create the YAMLIOHelper
    # subclass of the JSONIOHelper class (which is REALLY simple) and register it as a recognized format.
    from yaml import load as yamlLoad, dump as yamlDump
    try:
        from yaml import CLoader as yamlLoader, CDumper as yamlDumper
    except ImportError:
        from yaml import Loader as yamlLoader, Dumper as yamlDumper

    class YAMLIO(BaseIO):

        def readExamData(self, inputFPtr):
            return yamlLoad(inputFPtr, Loader=yamlLoader)
    
        def writeExamDataAndSummaries(self, outputFPtr, examData):
            document = examData.exportAsDict()
            yamlDump(document, stream=outputFPtr, Dumper=yamlDumper, indent=4)

    inputFormatsRecognized['yaml'] = lambda:YAMLIO()
    outputFormatsRecognized['yaml'] = lambda:YAMLIO()

except:
    pass

##
####
##

class FortranIO(BaseIO):
    
    # The answer key will be printed by breaking the list into groups of this many values:
    answerKeyStride = 5
    
    # This is the answerKeyStride written out in all caps:
    answerKeyStrideStr = 'FIVE'

    # The student answers Fortran format string needs to be broken-down into (<COUNT>)?(I|T)<WIDTH> units:
    fieldRegex = re.compile('(\d+)?([IT])(\d+)')

    def stringToIntWithDefault(self, s, default=0):
        """Attempt to convert a string to an integer, returning the default value if the conversion fails."""
        try:
            return int(s)
        except:
            return default

    def nextNonEmptyLineInFile(self, fptr):
        """Returns the next non-blank (whitespace only) line from the given file.  Raises EOFError when the end of file is reached."""
        while True:
            line = fptr.readline()
            if len(line) == 0:
                # End of file
                raise EOFError()
            if line.strip():
                break
        return line.rstrip()
    
    def parseStudentDataLine(self, formattingSpecs, studentDataLine, prevScore=None, prevAnswers=None):
        score = prevScore if (prevScore is not None) else None
        answers = prevAnswers if (prevAnswers is not None) else []
        lastIndex = 0
        fieldIndex = 0
        for field in formattingSpecs:
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

    def readExamData(self, inputFPtr):
        #
        # Read the file header, which supplies the instructor, course, etc.
        #
        values = self.nextNonEmptyLineInFile(inputFPtr)
        
        #(I4,2A10,5X,3I2,1X,I4,2X,I3,3(4X,I1), I1,3X,I1 )
        examId = self.stringToIntWithDefault(values[0:4])
        if examId == 0:
            # A zero examId implies end of the exam data:
            return False
            
        examDate = datetime.datetime.strptime(values[29:35], '%m%d%y')
        
        # Create a new exam object and fill-in its instance data from the header we just read:
        newExam = Exam()
            
        newExam.setExamId(examId)                                       # 4-digit arbitrary id
        newExam.setCourseName(values[4:14])                             # Course identifier
        newExam.setInstructor(values[14:24])                            # Instructor identifier
        newExam.setExamDate(examDate)                                   # Raw date is MMDDYY with implied century
        
        # Generate the Options for the full exam and first section:
        idig = self.stringToIntWithDefault(values[56:61])               # 1 = forward order (A, B, ...), 2 = reverse order (E, D, ...)
        if idig not in (1, 2):
            raise ValueError('Ordering specifier {:d} no in set (1=forward, 2=reverse).'.format(idig))    
        ncopy = self.stringToIntWithDefault(values[62:])                # Number of copies (0, 1, 2)
        if ncopy < 0:
            ncopy = 0
        if ncopy > 2:
            ncopy = 2
        newExam.setOptions(Options(fromDict={
                'is-order-reversed': (idig == 2),
                'number-of-copies': ncopy,
                'should-eval-full-exam-only': (self.stringToIntWithDefault(values[46:51]) == 0)      # 0 = test summary only, 1=question + test summary
            }))
        
        #
        # At this point, we're ready to loop over exam sections:
        #
        sectionCount = 0
        while True:
            #
            # The 'values' variable contains the last-read header line; pull the exam section's
            # dimensions from that:
            #
            nStudents = self.stringToIntWithDefault(values[35:41])      # Number of exam responses
            nQuestions = self.stringToIntWithDefault(values[41:46])     # Number of questions on exam
            
            # Create the exam section now:
            examSection = ExamSection()
            
            # Generate options for section:
            idig = self.stringToIntWithDefault(values[56:61])               # 1 = forward order (A, B, ...), 2 = reverse order (E, D, ...)
            if idig not in (1, 2):
                raise ValueError('Ordering specifier {:d} no in set (1=forward, 2=reverse).'.format(idig))
            ncopy = self.stringToIntWithDefault(values[62:])                # Number of copies (0, 1, 2)
            if ncopy < 0:
                ncopy = 0
            if ncopy > 2:
                ncopy = 2
            newExam.setOptions(Options(fromDict={
                    'is-order-reversed': (idig == 2),
                    'number-of-copies': ncopy,
                    'should-eval-full-exam-only': (self.stringToIntWithDefault(values[46:51]) == 0)      # 0 = test summary only, 1=question + test summary
                }))
            
            # Read the answer key for this section:
            n = nQuestions
            answerKey = []
            while n > 0:
                values = [int(x) for x in self.nextNonEmptyLineInFile(inputFPtr).strip()]
                answerKey.extend(values)
                n -= len(values)
            if n != 0:
                raise ValueError('Answer key dimension {:d} does not match question count {:d} specified in header.'.format(len(values), nQuestions))
            examSection.setAnswerKey(answerKey)
            
            # Read the response format string and convert to a list of formatting spec dicts:
            formattingString = self.nextNonEmptyLineInFile(inputFPtr).strip()
            examSection.setFortranFormatString(formattingString)
            formattingSpecs = []
            fieldIndex = 1
            for formatField in formattingString.strip('()').split(','):
                m = self.fieldRegex.match(formatField)
                if m is None:
                    raise ValueError('Invalid field format at item {:d} in {:s}'.format(fieldIndex, formattingString))
                formattingSpecs.append({
                            'width': int(m.group(3)),
                            'count': int(m.group(1)) if m.group(1) else 1,
                            'type':  m.group(2)
                        })
                fieldIndex += 1
            
            n = nStudents
            score = None
            answers = []
            groupId = 1
            answersGroup = StudentAnswers()
            answersGroup.setGroupId(groupId)
            while n > 0 and groupId < 6:
                (score, answers) = self.parseStudentDataLine(formattingSpecs, self.nextNonEmptyLineInFile(inputFPtr), score, answers)
                if score == -1:
                    # New group:
                    if groupId >= 6:
                        raise ValueError('More than 5 student groups present in input file.')
                    if answersGroup.studentCount() > 0:
                        examSection.addStudentAnswers(answersGroup)
                    groupId += 1
                    answersGroup = StudentAnswers()
                    answersGroup.setGroupId(groupId)
                    score = None
                    answers = None
                else:
                    if len(answers) >= nQuestions:
                        answersGroup.appendStudentData(score, answers)
                        score = None
                        answers = []
                        n -= 1
            if n != 0:
                raise ValueError('Unable to locate {:d} student answers in the input file.'.format(n))
            # Tack-on the final student group we were making:
            if answersGroup.studentCount() > 0:
                examSection.addStudentAnswers(answersGroup)
            
            # Consume however many new-group lines remain:
            while groupId < 6:
                (score, answers) = self.parseStudentDataLine(formattingSpecs, self.nextNonEmptyLineInFile(inputFPtr))
                if score != -1:
                    raise ValueError('Unable to consume new-group token {:d} from input file'.format(groupId))
                groupId += 1
                
            # We've completed reading the section, so add it to the exam:
            newExam.addExamSection(examSection)
            sectionCount += 1
            
            # Try to read another section from the file:
            try:
                values = self.nextNonEmptyLineInFile(inputFPtr)
            except EOFError as E:
                # End-of-file pretty clearly means there's no more sections to read...
                break
            except Exception as E:
                # ...but any other error isn't a problem we can foresee:
                raise E
            
            #(I4,2A10,5X,3I2,1X,I4,2X,I3,3(4X,I1), I1,3X,I1 )
            examId = self.stringToIntWithDefault(values[0:4])
            if examId == 0:
                break
            
        return newExam
        
    def writeExamSection(self, outputFPtr, examData, examSection):
        #  210  FORMAT (' ',33X, 'ITEM ANALYSIS FOR DATA HAVING SPECIFIABLE RIGHT-
        #      1WRONG ANSWERS' ///// 33X, 'THE USER HAS SPECIFIED THE FOLLOWING IN
        #      2FORMATION ON CONTROL CARDS' //// 20X,'JOB NUMBER',I6 //20X,
        #      3 'COURSE  ',A10 //20X,'INSTRUCTOR  ',A10 //20X,'DATE (MONTH, DAY,
        #      4YEAR)  ',3I4  )
        examDate = examData.examDate()
        outputText = '                                  ITEM ANALYSIS FOR DATA HAVING SPECIFIABLE RIGHT-WRONG ANSWERS\n\n\n\n\n                                 THE USER HAS SPECIFIED THE FOLLOWING INFORMATION ON CONTROL CARDS\n\n\n\n                    JOB NUMBER{:>6.6s}\n\n                    COURSE  {:10.10s}\n\n                    INSTRUCTOR  {:10.10s}\n\n                    DATE (MONTH, DAY, YEAR)  {:4d}{:4d}{:>4s}\n'.format(
                        examData.examId(), examData.courseName(), examData.instructor(),
                        examDate.month if examDate else 0, examDate.day if examDate else 0, examDate.strftime('%y') if examDate else 'XX')
                    
        fortranFormatString = examSection.fortranFormatString()
        responsesPerQuestion = examSection.responsesPerQuestion()
        
        #   220 FORMAT (/ 20X, 'NUMBER OF STUDENTS', I6  //20X,'NUMBER OF ITEMS',
        #      1 I5// 20X,'ITEM EVALUATION OPTION (0=NO, 1=YES)', I4 //20X,
        #      3 'MAXIMUM NUMBER OF ANSWER CHOICES', I4/)
        outputText += '\n                    NUMBER OF STUDENTS{:6d}\n\n                    NUMBER OF ITEMS{:5d}\n\n                    ITEM EVALUATION OPTION (0=NO, 1=YES){:4d}\n\n                    MAXIMUM NUMBER OF ANSWER CHOICES{:4d}\n\n\n                         INPUT FORMAT   {:72.72s}\n'.format(
                        examData.totalStudentCount(), examSection.questionCount(), 0 if examSection.options()['should-eval-full-exam-only'] else 1, examSection.responsesPerQuestion(),
                        fortranFormatString if fortranFormatString else '-- NON-FORTRAN INPUT --')
        
        if examSection.options()['is-order-reversed']:
            #  242  FORMAT (/25X,'INPUT FORMAT',3X, A72 / 25X,'RESPONSE FORM', I2,
            #      1 '=A,', I2,'=B, ...'  )
            #
            # moved input format to previous write()
            outputText += '                         RESPONSE FORM{:2d}=A,{:2d}=B, ...\n'.format(
                            responsesPerQuestion, responsesPerQuestion - 1)
        else:
            #  241  FORMAT (/25X,'INPUT FORMAT', 3X,A72 / 25X,'RESPONSE FORM  1=A, 2=
            #      1B, 3=C, ...ETC' )
            #
            # moved input format to previous write()
            outputText += '                         RESPONSE FORM  1=A, 2= B, 3=C, ...ETC\n'
        
        #  250  FORMAT (                             /20X,'NUMBER OF COPIES OF OUT
        #      1PUT (MAX. ALLOWED=2)', I3 //20X,'CORRECT ANSWERS IN GROUPS OF FIVE
        #      2' /2(25X,15(5I1,1X) /)  )
        outputText += '\n                    NUMBER OF COPIES OF OUTPUT (MAX. ALLOWED=2){:3d}\n\n                    CORRECT ANSWERS IN GROUPS OF {:s}\n'.format(
                        examSection.options()['number-of-copies'], self.answerKeyStrideStr)
        answerKey = examSection.answerKey()
        answerChunkCount = len(answerKey)
        answerChunkCount = int((answerChunkCount + (self.answerKeyStride - 1)) / self.answerKeyStride)
        inRowMax = int(90 / (self.answerKeyStride + 1))
        answerChunkIdx = 0
        while answerChunkIdx < answerChunkCount:
            inRowIdx = 0
            outputText += '                         '
            while answerChunkIdx < answerChunkCount and inRowIdx < inRowMax:
                outputText += '{:s}{:s}'.format(
                        ''.join([str(i) for i in answerKey[answerChunkIdx * self.answerKeyStride:(answerChunkIdx + 1) * self.answerKeyStride]]),
                        (' ' if ((inRowIdx + 1 < inRowMax) and (answerChunkIdx + 1 < answerChunkCount)) else '\n'))
                answerChunkIdx += 1
                inRowIdx += 1
            
        outputText += '1\n'
        
        statsData = examSection.statisticalSummary()
        if statsData is not None:
             # New page token:
            outputText += '1\n'
            
            # Loop over questions:
            q = 0
            while q < len(statsData):
                question = statsData[q]
                q += 1
                
                if question['should-insert-new-page']:
                    # '1',15X,'ITEM NUMBER',I4,8X,'CORRECT ANSWER AND ITEM DIFFICULTY INDEX ARE IDENTIFIED BY  * ' /
                    outputText += '1               ITEM NUMBER{:4d}        CORRECT ANSWER AND ITEM DIFFICULTY INDEX ARE IDENTIFIED BY  * \n\n'.format(q)
                else:
                    # ' ',15X,'ITEM NUMBER',I4,8X,'CORRECT ANSWER AND ITEM DIFFICULTY INDEX ARE IDENTIFIED BY  * ' /
                    outputText += '                ITEM NUMBER{:4d}        CORRECT ANSWER AND ITEM DIFFICULTY INDEX ARE IDENTIFIED BY  * \n\n'.format(q)
                

                # '   OPTIONS',5X,'1ST',4X,'2ND',4X,'3RD',4X,'4TH',4X,'5TH',3X,'RESPONSE',4X,'PROPORTION',4X,'MEAN',6X,'OPTIONS'/ 14X,'GROUP',2X,'GROUP',2X,'GROUP',2X,'GROUP',2X,'GROUP',4X,'TOTAL',6X,'CHOOSING',5X,'SCORE',3X,'QUESTIONABLE'
                outputText += '   OPTIONS     1ST    2ND    3RD    4TH    5TH   RESPONSE    PROPORTION    MEAN      OPTIONS\n              GROUP  GROUP  GROUP  GROUP  GROUP    TOTAL      CHOOSING     SCORE   QUESTIONABLE\n'
            
                j = 1
                # 3X,'*',4HOMIT,5X,I3,4X,I3,4X,I3,4X,I3,4X,I3,5X,I4,8X,'*',F6.3,6X,F6.2
                # 1H ,3X,4HOMIT,5X,I3,4X,I3,4X,I3,4X,I3,4X,I3,5X,I4,9X,F6.3,6X,F6.2
                answer = question['omitted']
                badge = ('*' if answer['is-correct-answer'] else ' ')
                countByGroup = answer['count-by-group']
                if len(countByGroup) < 5:
                    countByGroup.extend([0]*(5 - len(countByGroup)))
                outputText += '   {:s}OMIT     {:3d}    {:3d}    {:3d}    {:3d}    {:3d}     {:4d}        {:1s}{:6.3f}      {:6.2f}\n'.format(
                            badge,
                            countByGroup[0], countByGroup[1], countByGroup[2], countByGroup[3], countByGroup[4],
                            answer['total-responses'], badge, answer['chosen-by-ratio'], answer['mean-score'])
                
                # Go through the exam answers list:
                for byAnswerKey in sorted(question['by-answer'].keys()):
                    answer = question['by-answer'][byAnswerKey]
                    j = answer['index']
                    if examSection.options()['is-order-reversed']:
                        K = examSection.responsesPerQuestion() + 1 - j
                    else:
                        K = j
                    
                    # 2X,'*',A1,' OR ',I1,4X,I3,4(4X,I3),5X,I4,8X,'*',F6.3,6X,F6.2,8X,A1
                    badge = ('*' if answer['is-correct-answer'] else ' ')
                    countByGroup = answer['count-by-group']
                    if len(countByGroup) < 5:
                        countByGroup.extend([0]*(5 - len(countByGroup)))
                    outputText += '  {:s}{:1.1s} OR {:1d}    {:3d}    {:3d}    {:3d}    {:3d}    {:3d}     {:4d}        {:s}{:6.3f}      {:6.2f}        {:1.1s}\n'.format(
                                badge, Exam.answerSymbolByIndex[j], K,
                                countByGroup[0], countByGroup[1], countByGroup[2], countByGroup[3], countByGroup[4],
                                answer['total-responses'], badge, answer['chosen-by-ratio'], answer['mean-score'], '?' if answer['is-questionable'] else ' ')
                        
                # 1H0,2X,5HTOTAL,5X,I3,4X,I3,4X,I3,4X,I3,4X,I3,5X,I4
                countByGroup = question['total']['count-by-group']
                if len(countByGroup) < 5:
                    countByGroup.extend([0]*(5 - len(countByGroup)))
                outputText += '0  TOTAL     {:3d}    {:3d}    {:3d}    {:3d}    {:3d}     {:4d}\n'.format(
                        countByGroup[0], countByGroup[1], countByGroup[2], countByGroup[3], countByGroup[4], question['total']['total-responses'])
                
                # 1H0,'BISERIAL CORRELATION BETWEEN ITEM SCORE AND TOTAL SCORE ON TEST = ',F6.3
                outputText += '0BISERIAL CORRELATION BETWEEN ITEM SCORE AND TOTAL SCORE ON TEST = {:6.3f}\n'.format(
                        question['biserial-correlation'])
                
                # 1H ,29HPOINT-BISERIAL CORRELATION = ,F6.3,14X,4HT = ,F6.3///
                outputText += ' POINT-BISERIAL CORRELATION = {:6.3f}              T = {:6.3f}\n\n\n\n'.format(
                        question['pointwise-biserial-correlation'], question['t-value'])
        
                if exam.options()['should-eval-full-exam-only']:
                    # 1H ,///
                    outputText += ' \n\n\n\n'
        
        outputFPtr.write(outputText*examSection.options()['number-of-copies'])
    
    def writeExamDataAndSummaries(self, outputFPtr, examData):
        for examSection in examData.examSections():
            # Write header for the exam section:
            self.writeExamSection(outputFPtr, examData, examSection)
            
        statsData = exam.statisticalSummary()
        
        # '1',50X,'ADDITIONAL TEST INFORMATION'//// 15X,'THE MEAN ITEM DIFFICULTY FOR THE ENTIRE TEST =',F7.3//15X,'THE MEAN ITEM SCORE - TOTAL SCORE BISERIAL CORRELATION =', F6.3
        outputText = '1                                                  ADDITIONAL TEST INFORMATION\n\n\n\n               THE MEAN ITEM DIFFICULTY FOR THE ENTIRE TEST ={:7.3f}\n\n               THE MEAN ITEM SCORE - TOTAL SCORE BISERIAL CORRELATION ={:6.3f}\n'.format(
                statsData['mean-difficulty'], statsData['total-biserial-correlation'])
    
        # /15X,'KUDER-RICHARDSON 20 RELIABILITY =',F7.3//  15X,'TEST MEAN =',F7.2, '   VARIANCE =', F10.2,  '   STANDARD DEVIATION =',F7.2 /
        outputText += '\n               KUDER-RICHARDSON 20 RELIABILITY ={:7.3f}\n\n               TEST MEAN ={:7.2f}   VARIANCE ={:10.2f}   STANDARD DEVIATION ={:7.2f}\n\n'.format(
                statsData['kuder-richardson-20-reliability'], statsData['score-mean'], statsData['score-variance'], statsData['score-std-deviation'])
    
        # 15X,'STANDARD ERROR OF MEASUREMENT (BASED ON KR-20) =',F7.2//  15X,'NUMBER OF STUDENTS =',I5,8X,'NUMBER OF ITEMS ON TEST =',I5////
        outputText += '               STANDARD ERROR OF MEASUREMENT (BASED ON KR-20) ={:7.2f}\n\n               NUMBER OF STUDENTS ={:5d}        NUMBER OF ITEMS ON TEST ={:5d}\n\n\n\n\n'.format(
                statsData['std-error-of-measurement-kr-20'], statsData['total-students'], statsData['total-questions'])
    
        # ' ',10X,'DISTRIBUTION OF THE TEST ITEMS',39X,'DISTRIBUTION OF THE TEST ITEMS'/ ' IN TERMS OF THE PERCENTAGE OF STUDENTS',' PASSING THEM', 14X,'IN TERMS OF ITEM SCORE - TOTAL SCORE BISERIAL CORRELATIONS'/// 6X,'PERCENT PASSING',11X,'NUMBER OF ITEMS',33X, 'CORRELATIONS', 4X,'NUMBER OF ITEMS'
        outputText += '           DISTRIBUTION OF THE TEST ITEMS                                       DISTRIBUTION OF THE TEST ITEMS\n'
        outputText += ' IN TERMS OF THE PERCENTAGE OF STUDENTS PASSING THEM              IN TERMS OF ITEM SCORE - TOTAL SCORE BISERIAL CORRELATIONS\n\n\n'
        outputText += '      PERCENT PASSING           NUMBER OF ITEMS                                 CORRELATIONS    NUMBER OF ITEMS\n'
    
        # '0',10X,'0 - 19',20X,I3,39X,'NEGATIVE - .10',8X,I3)
        outputText += '0          0 - 19                    {:3d}                                       NEGATIVE - .10        {:3d}\n'.format(
                statsData['distribution-by-passing'][0]['item-count'], statsData['distribution-by-biserial-correlation'][0]['item-count'])
    
        # ' ',9X,'20 - 39',20X,I3,42X,'.11 - .30',10X,I3)
        outputText += '          20 - 39                    {:3d}                                          .11 - .30          {:3d}\n'.format(
                statsData['distribution-by-passing'][1]['item-count'], statsData['distribution-by-biserial-correlation'][1]['item-count'])
    
        # ' ',9X,'40 - 59',20X,I3,42X,'.31 - .50',10X,I3)
        outputText += '          40 - 59                    {:3d}                                          .31 - .50          {:3d}\n'.format(
                statsData['distribution-by-passing'][2]['item-count'], statsData['distribution-by-biserial-correlation'][2]['item-count'])
    
        # ' ',9X,'60 - 79',20X,I3,42X,'.51 - .70',10X,I3)
        outputText += '          60 - 79                    {:3d}                                          .51 - .70          {:3d}\n'.format(
                statsData['distribution-by-passing'][3]['item-count'], statsData['distribution-by-biserial-correlation'][3]['item-count'])
    
        # ' ',9X,'80 -100',20X,I3,42X,'.71 - .90',10X,I3
        outputText += '          80 -100                    {:3d}                                          .71 - .90          {:3d}\n'.format(
                statsData['distribution-by-passing'][4]['item-count'], statsData['distribution-by-biserial-correlation'][4]['item-count'])
        
        # ' ',81X,'.91 -    ',10X,I3/ ////40X,'CHOICES',5X,'% KEYED',5X,'% CHOSEN',5X,'AVG. DIFF.'  /
        outputText += '                                                                                  .91 -              {:3d}\n\n\n\n\n                                        CHOICES     % KEYED     % CHOSEN     AVG. DIFF.\n\n'.format(
                statsData['distribution-by-biserial-correlation'][5]['item-count'])
        
        for answerSymbol in sorted(statsData['breakdown-by-choice'].keys()):
            # (43X,A1,9X,F5.3,8X,F5.3,9X,F5.3)
            breakdown = statsData['breakdown-by-choice'][answerSymbol]
            outputText += '                                           {:1.1s}         {:5.3f}        {:5.3f}         {:5.3f}\n'.format(
                    answerSymbol, breakdown['pct-keyed'], breakdown['pct-chosen'], breakdown['avg-difficulty'])
    
        # //10X,'% KEYED= FREQUENCY OF A GIVEN KEY DIVIDED BY THE NUMBER OF ITEMS.'/ 10X,'% CHOSEN= FREQUENCY OF A GIVEN RESPONSE DIVIDED BY THE TOTAL NUMBER OF RESPONSES TO ALL ITEMS (EXCLUDING OMITS).'/ 10X,'AVG. DIFF.= TOTAL OF ALL DIFFICULTY VALUES FOR ITEMS WITH A GIVEN KEY DIVIDED BY THE NUMBER OF SUCH ITEMS.'
        outputText += '\n\n          % KEYED= FREQUENCY OF A GIVEN KEY DIVIDED BY THE NUMBER OF ITEMS.\n'
        outputText += '          % CHOSEN= FREQUENCY OF A GIVEN RESPONSE DIVIDED BY THE TOTAL NUMBER OF RESPONSES TO ALL ITEMS (EXCLUDING OMITS).\n'
        outputText += '          AVG. DIFF.= TOTAL OF ALL DIFFICULTY VALUES FOR ITEMS WITH A GIVEN KEY DIVIDED BY THE NUMBER OF SUCH ITEMS.\n'

        for copyNum in range(exam.options()['number-of-copies']):
            outputFPtr.write(outputText)


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
        help='file format to read and write (fortran is the default): ' + ', '.join(inputFormatsRecognized.keys())
    )
cliParser.add_argument('--input-format', '-I',
        dest='inputFileFormat',
        help='file format to read (fortran is the default): ' + ', '.join(inputFormatsRecognized.keys())
    )
cliParser.add_argument('--output-format', '-O',
        dest='outputFileFormat',
        help='file format to write (fortran is the default): ' + ', '.join(outputFormatsRecognized.keys())
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
if fileFormat not in inputFormatsRecognized:
    sys.stderr.write('ERROR:  file format "{:s}" is not available for input\n'.format(cliArgs.fileFormat))
    sys.exit(errno.EINVAL)
inputFileFormat = fileFormat
if cliArgs.inputFileFormat:
    inputFileFormat = cliArgs.inputFileFormat.lower()
    if inputFileFormat not in inputFormatsRecognized:
        sys.stderr.write('ERROR:  file format "{:s}" is not available for input\n'.format(cliArgs.inputFileFormat))
        sys.exit(errno.EINVAL)
outputFileFormat = fileFormat
if cliArgs.outputFileFormat:
    outputFileFormat = cliArgs.outputFileFormat.lower()
    if outputFileFormat not in outputFormatsRecognized:
        sys.stderr.write('ERROR:  file format "{:s}" is not available for output\n'.format(cliArgs.outputFileFormat))
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
        inputHelper = inputFormatsRecognized[inputFileFormat]()
        outputHelper = outputFormatsRecognized[outputFileFormat]()
        
        exam = inputHelper.readExamData(inputFPtr)
        exam.reverseAnswerOrderingIfNecessary()

        stats = StatData()
        stats.processExam(exam)

        outputHelper.writeExamDataAndSummaries(outputFPtr, exam)
                    
    except Exception as E:
        print('ERROR:  ' + str(E))
        sys.exit(1)
