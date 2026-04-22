"""
varvis_connector data models module

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

from datetime import datetime, date
from typing import Any, Literal, Annotated

from pydantic import BaseModel, Field, ConfigDict


SampleOriginType = Literal["GERMLINE", "SOMATIC", "UNKNOWN", "SNPID", "MASKED"]
AnalysisType = Literal[
    "SNV",
    "SANGER_MUT_SURVEYOR",
    "CNV",
    "QPCR",
    "SV",
    "MSI",
    "PATHO_UI_SV",
    "PATHO_UI_MSI",
    "STR",
]
AnalysisStatus = Literal["PENDING", "DONE", "FAILED"]


class GenomicPosition(BaseModel):
    """Genomic position representation."""

    chromosome: str
    start: int
    end: int


class VariantSignificance(BaseModel):
    """Model representing variant significance."""

    id: int
    name: str


class HpoTerm(BaseModel):
    """HPO term representation."""

    accessionId: int
    name: str
    abbreviation: str | None = None


class ThresholdSettings(BaseModel):
    """Threshold settings for CNV target results."""

    homDelThreshold: float | None = None
    hetDelThreshold: float | None = None
    dupThreshold: float | None = None
    multiDupThreshold: float | None = None


class BaseHeaderItem(BaseModel):
    """
    General header item used as base for ``SnvAnnotationHeaderItem`` and ``CnvHeaderItem``.
    """

    id: str
    title: str
    description: str | None = None
    badge: str | None = None
    url: str | None = None
    dataDictionary: dict[str | int, Any] | None = None
    dataType: str | None = None
    fromMultiValue: bool | None = None


class CnvHeaderItem(BaseHeaderItem):
    property: str | None = None  # for CNV, this takes a string value


class SnvAnnotationHeaderItem(BaseHeaderItem):
    """
    Variant annotation header item as provided in "header" field of ``SnvAnnotationData``.
    """

    property: int | None = None  # for SNV, this takes an integer value
    bioinfScoreThresholdsByAnalysisId: dict[str, dict[str, Any]] | None = None
    category: (
        Literal[
            "META_SCORE",
            "SCORE_WITH_THRESHOLD",
            "SCORE_WITHOUT_THRESHOLD",
            "SPLICING_SCORE",
        ]
        | None
    ) = None


class SnvAnnotationData(BaseModel):
    """
    SNV annotation data as provided by varvis *Get variant annotations* endpoint.
    """

    header: list[SnvAnnotationHeaderItem]
    data: list[list]
    uniquePersonLabelSuffixes: dict[str, str] | None = None
    uniqueCnvPersonLabelSuffixes: dict[str, str] | None = None
    filterApplied: bool | None = None
    thresholdViolated: bool | None = None
    threshold: int | None = None


class CnvTargetResults(BaseModel):
    """CNV target results as provided by varvis *Get CNV results* endpoint."""

    targetRegionsHeader: list[CnvHeaderItem]
    data: list[list]
    bivariance: float | None = None
    maxValidBivariance: float | None = None
    meanCoverage: float | None = None
    refSpreadThreshold: float | None = None
    sex: Literal["Male", "Female", "Unknown", "Intersex"] | None = None
    thresholds: ThresholdSettings
    segmentationThresholds: ThresholdSettings
    uniquePersonLabelSuffixes: dict[str, str]
    wgs: bool
    geneIdToHpoTerms: dict[str, list[HpoTerm]]
    geneIdToHpoMoiTerms: dict[str, list[HpoTerm]]
    geneIdToHpoMatchedTerms: dict[str, list]
    geneIdToHpoSimScore: dict[str, float]


class CnvAnnotations(BaseModel):
    """
    CNV Annotation representation used in ``PendingCnvDataItem`` and in ``CaseReportCnvConclusion``.

    Note that this model was only inferred from sample data retrieved from the varvis playground and as shown in the
    varvis documentation. The varvis documentation does not provide any information about the actual structure of this
    data.
    """

    model_config = ConfigDict(populate_by_name=True)

    DGV_found: int | list[Any] | None = Field(default=None, alias="DGV:found")
    DGV_subtype: list[str] | None = Field(default=None, alias="DGV:subtype")
    DECIPHER_sig: list[str] | str | None = Field(default=None, alias="DECIPHER:sig")
    DECIPHER_type: list[str] | str | None = Field(default=None, alias="DECIPHER:type")
    DECIPHER_found: int | list[Any] | None = Field(default=None, alias="DECIPHER:found")
    ALLEXES_CNV_sig_gain: list[str] | str | None = Field(
        default=None, alias="ALLEXES_CNV:sig_gain"
    )
    ALLEXES_CNV_sig_loss: list[str] | str | None = Field(
        default=None, alias="ALLEXES_CNV:sig_loss"
    )
    ALLEXES_CNV_found_gain: int | None = Field(
        default=None, alias="ALLEXES_CNV:found_gain"
    )
    ALLEXES_CNV_found_loss: int | None = Field(
        default=None, alias="ALLEXES_CNV:found_loss"
    )
    localFoundGain: int | None = None
    localFoundLoss: int | None = None
    localSignificanceGain: list[Any] | str | None = None
    localSignificanceLoss: list[Any] | str | None = None


class CnvRelativesDataItem(BaseModel):
    """CNV relatives data representation used in ``PendingCnvDataItem``."""

    copyNumbers: list[int]
    types: list[Literal["LOSS", "GAIN"]]


class PendingCnvDataItem(BaseModel):
    """
    Pending CNV data item used in ``PendingCnvData`` model.

    Note that this model was only inferred from sample data retrieved from the varvis playground and as shown in the
    varvis documentation. The varvis documentation does not provide any information about the actual structure of this
    data.
    """

    index: bool
    pendingCnvId: int
    detectedSegmentId: int | None = None
    log2Value: float
    refSpread: float
    copyNumber: int
    type: Literal["LOSS", "GAIN"] | None = (
        None  # based on the example, assuming only LOSS or GAIN
    )
    position: GenomicPosition
    regionInfo: str | None = None
    exactBreakpointBegin: bool
    exactBreakpointEnd: bool
    cytoband: str
    cdna: str | None = None
    regionIndexBegin: int
    regionIndexEnd: int
    mosaic: bool
    mosaicRelation: str | None = (
        None  # unsure about this type; only every saw "null" in sample data
    )
    analysisId: int
    relativeAnalysisIds: list[int]
    comment: str | None = None
    iscn: str
    hgvs: str
    inheritance: str
    geneIds: list[int]
    transcriptNcbiIds: list[str]
    exons: list[int]
    localFoundGain: int
    localFoundLoss: int
    localSignificanceGain: list[Any] = []
    localSignificanceLoss: list[Any] = []
    overlapOperator: Literal[
        "AND", "OR"
    ]  # unsure about these possible values; only every saw "AND" in sample data
    overlapParam: float
    otherOverlapParam: float
    commentCount: int
    recentComment: str | None = (
        None  # unsure about this type; only every saw "null" in sample data
    )
    annotations: CnvAnnotations
    relativesData: dict[str, CnvRelativesDataItem] = {}


class PendingCnvData(BaseModel):
    """Pending CNV data as returned from varvis pending-cnv endpoint."""

    data: list[PendingCnvDataItem]
    cnvHeader: list[CnvHeaderItem]


class QCCaseMetricResultGroupingKey(BaseModel):
    """
    Model representing a grouping key for a QC case metric result data item.

    Used in ``QCCaseMetricResultDataItem`` model.
    """

    type: str
    lane: str | None = None
    linkedAnalysisId: int | None = None


class QCCaseMetricResultDataItem(BaseModel):
    """
    Model representing a single data item in a QC case metric result.

    Used in ``QCCaseMetricResultItem`` model.
    """

    analysisId: int | None = None
    sequencingBatchId: int | None = None
    dimension: str  # e.g., "SAMPLE_SIMILARITY_SCORE", "BASE_QUALITY_SCORE_MEAN"
    data: float | int | str | dict[str, float | int]
    groupingKey: QCCaseMetricResultGroupingKey | None = None
    violated: bool
    mappedData: float | int | str | dict | None = None
    linkedAnalysisId: int | None = None
    type: str | None = None


class QCCaseMetricResultItem(BaseModel):
    """
    Model representing a single QC case metric result.

    Used in ``QCCaseMetricResults`` model.
    """

    analysisId: int | None = None
    referenceAnalysisId: int | None = None
    sequencingBatchId: int | None = None
    sampleId: str | None = None
    qualityMetricTypes: list[int]
    data: dict[str, QCCaseMetricResultDataItem]


class QCCaseMetricResults(BaseModel):
    """
    Model representing QC case metrics results.

    Used in ``QCCaseMetricsData`` model.
    """

    personId: str
    sampleIds: dict[str, str]
    metricResults: list[QCCaseMetricResultItem]
    sequencingBatchesMetricResults: list[QCCaseMetricResultItem]


class QCCaseMetricTypeDimension(BaseModel):
    """Dimension model for QCCaseMetricType"""

    id: int
    name: str
    description: str | None = None
    grid: bool
    chart: bool
    threshold: bool


class QCCaseMetricType(BaseModel):
    """
    Model representing a quality metric type in QC case metrics with its dimensions.

    Used in ``QCCaseMetricsData`` model.
    """

    id: int
    type: str  # e.g., "DEMULTIPLEXING", "COVERAGE", "SNV", etc.
    title: str
    description: str
    dimensions: list[QCCaseMetricTypeDimension]
    chartTitle: str | None = None


class QCCaseMetricThresholdRangeBound(BaseModel):
    """
    Represents the threshold bounds for a specific dimension in QC case metrics threshold ranges.

    Used in ``QCCaseMetricThresholdRanges`` model.
    """

    lowerBound: float | None = None
    upperBound: float | None = None
    defaultLowerBound: float | None = None
    defaultUpperBound: float | None = None
    fixedValues: bool


class QCCaseMetricThresholdRangeCategory(BaseModel):
    """
    Model representing a category in QC case metrics threshold ranges.

    Used in ``QCCaseMetricThresholdRanges`` model.
    """

    id: int
    title: str
    description: str
    name: str
    types: list[QCCaseMetricType]
    order: int


class QCCaseMetricEnrichmentKitDisabledAnnotationField(BaseModel):
    name: str
    displayName: str


class QCCaseMetricEnrichmentKit(BaseModel):
    """
    Model representing an enrichment kit in QC case metrics threshold ranges.

    Used in ``QCCaseMetricEnrichmentKit`` model.
    """

    id: int
    bedFile: str
    bedRegionsSize: int
    canBeDeleted: bool
    disabledAnnotationFields: list[QCCaseMetricEnrichmentKitDisabledAnnotationField]
    name: str


class QCCaseMetricThresholdRanges(BaseModel):
    """
    Model representing threshold ranges for metrics along with enrichment kits and categories.

    Used in ``QCCaseMetricsData`` model.
    """

    enrichmentKits: list[QCCaseMetricEnrichmentKit]
    categories: list[QCCaseMetricThresholdRangeCategory]
    ranges: dict[str, dict[str, QCCaseMetricThresholdRangeBound]]


class QCCaseMetricsData(BaseModel):
    """QC case metrics data model as returned from varvis get case metrics endpoint."""

    metricResults: QCCaseMetricResults
    metricTypes: list[QCCaseMetricType]
    thresholdRanges: QCCaseMetricThresholdRanges


class CoverageData(BaseModel):
    """
    Coverage data model as returned from varvis get coverage endpoint.
    """

    chromosome: str
    start: int
    end: int
    length: int
    minimumCoverage: int
    maximumCoverage: int
    meanCoverage: float
    basePairsNotCovered: int
    percentCovered: float
    regionName: str
    sourceId: str
    analysisId: int
    laneQuality: str | None = None
    gene: str | None = None
    transcript: str | None = None
    exonNumbers: list[int] | None = None


class AnalysisApproval(BaseModel):
    """
    Analysis approval model as returned from varvis analyses endpoint. Used in `AnalysisItem`.

    Generated from API documentation.
    """

    analysisId: int
    userId: int | None = None
    userName: str
    approvalTime: datetime
    status: Literal["APPROVED", "REJECTED", "PENDING"] | None = None
    comment: str | None = None


class AnalysisItem(BaseModel):
    """
    An analysis item model as returned from varvis analyses endpoint.

    Generated from playground samples and API documentation.
    """

    id: int
    analysisType: AnalysisType  # according to API docs
    status: AnalysisStatus  # according to API docs
    regulatoryStatus: Literal[
        "UNKNOWN", "IN_VITRO_DIAGNOSTIC", "RESEARCH_USE_ONLY", "PERFORMANCE_STUDY_ONLY"
    ]
    sourceId: str | None = None
    sampleId: str | None = None
    sampleOrigin: SampleOriginType | None = None
    enrichmentKitName: str | None = None
    referencedAnalysisId: int | None = None
    personLimsId: str | None = None
    jobName: str | None = None
    analysisApproval: AnalysisApproval | None = None
    sequencingBatchId: int | None = None
    firstAnnotated: datetime | None = None
    lastAnnotated: datetime | None = None


class FindByInputFileNameAnalysisItem(BaseModel):
    """
    Analysis item model used in *Find By Input File Name* endpoint. Similar to ``AnalysisItem`` model but yet different.

    Generated from playground samples and API documentation.
    """

    analysisId: int
    personId: int | None = None
    enrichmentKitId: int | None = None
    analysisStatus: AnalysisStatus  # TODO: are these all possible options?
    matchingOriginalFileName: str | None = None
    matchingCustomerProvidedInputFilePath: str | None = None
    sampleOrigin: SampleOriginType  # as specified in API docs
    analysisType: AnalysisType  # as specified in API docs
    finishedDate: datetime


class PersonPersonalInformation(BaseModel):
    """
    Personal information model as used in ``PersonData`` model.
    """

    limsId: str | None = None
    familyId: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    comment: str | None = None
    sex: Literal["UNKNOWN", "MALE", "FEMALE", "INTERSEX"] | None = None
    birthDate: date | None = None
    country: str | None = None
    consentType: Literal["FULL_CONSENT", "NO_CONSENT", "UNKNOWN"] | None = None
    validationStatus: (
        Literal["UNKNOWN", "FLAGGED", "PROCESSED", "VALIDATED", "DELETING"] | None
    ) = None


class PersonHpoTermDiseaseModifier(BaseModel):
    """
    Modifier model as used in ``PersonHpoTerm`` and ``PersonDisease`` models.
    """

    accession: str
    name: str
    description: str
    synomys: list[str]


class PersonHpoTerm(BaseModel):
    """
    Person HPO term model as used in ``PersonClinicalInformation`` model.
    """

    accession: str
    name: str
    description: str
    synomys: list[str] | None = (
        None  # stated as "required" in API docs, but Varvis playground actually returns missing data here
    )
    presence: Literal["PRESENT", "ABSENT"]
    level: Literal["MAJOR", "MINOR", "UNKNOWN"]
    modifiers: list[PersonHpoTermDiseaseModifier]


class PersonDisease(BaseModel):
    """
    Person disease information model as used in ``PersonClinicalInformation`` model.
    """

    shortName: str | None = None
    name: str | None = None
    presence: Literal["PRESENT", "ABSENT"]
    level: Literal["MAJOR", "MINOR", "UNKNOWN"]
    modifiers: list[PersonHpoTermDiseaseModifier]


class PersonClinicalInformation(BaseModel):
    """
    Person clinical information model as used in ``PersonData`` model.
    """

    limsId: str | None = None
    hpoTerms: list[PersonHpoTerm] | None = None
    diseases: list[PersonDisease] | None = None
    consanguineous: bool | None = None
    parentageConfirmed: bool | None = None


class PersonData(BaseModel):
    """
    Model of person data as returned from varvis *Get Person Including Clinical Information* endpoint.

    Generated from sample responses and updated from Varvis API documentation.
    """

    personalInformation: PersonPersonalInformation
    clinicalInformation: PersonClinicalInformation


class PersonUpdateData(BaseModel):
    """
    Model for creating or updating a person entry using the *Api Create Or Update Person* endpoint.

    Allows to create a new person entry, or updates an existing one. Only the id field is required.
    Fields that are None will not override existing values on update.

    Generated from API documentation.
    """

    id: str = Field(
        description="The custom ID for this person, e.g. as used in the LIMS system."
    )
    familyId: str | None = Field(
        default=None, description="The ID of this person's family."
    )
    firstName: str | None = Field(default=None, description="The person's first name.")
    lastName: str | None = Field(default=None, description="The person's last name.")
    comment: str | None = Field(
        default=None, description="A free-text comment on the person."
    )
    sex: Literal["MALE", "FEMALE", "UNKNOWN", "INTERSEX"] | None = Field(
        default=None, description="The biological sex of the person."
    )
    birthDateYear: int | None = Field(
        default=None, description="The year of the birth date."
    )
    birthDateMonth: int | None = Field(
        default=None, description="The month of the birth date."
    )
    birthDateDay: int | None = Field(
        default=None, description="The day of the birth date."
    )
    country: str | None = Field(
        default=None, description="The name of the person's home country."
    )
    hpoTermIds: list[str] | None = Field(
        default=None, description="The list of the person's HPO term ids."
    )


class PersonReportItem(BaseModel):
    """
    Model representing a report item for the Varvis "Get Report Info For Persons" API endpoint.

    Generated from playground samples and API documentation.
    """

    limsId: str
    timeSubmitted: datetime | None = None
    timeApproved: datetime | None = None
    markedForApproval: bool | None = None


class CaseReportAnnotationSource(BaseModel):
    """
    Model representing an annotation source in a case report. Used in ``CaseReportAnalysis``.
    """

    name: str
    value: str


class CaseReportAnalysis(BaseModel):
    """
    Model representing an analysis in a case report person item. Used in ``CaseReportPersonItem``.
    """

    analysisId: int
    sampleId: str | None = None
    analysisType: AnalysisType | None = None  # according to API docs
    enrichmentKit: str | None = None
    sourceId: str | None = None
    annotationSources: list[CaseReportAnnotationSource]
    selected: bool


class CaseReportPersonItem(BaseModel):
    """
    Model representing a person item for a case report. Used in ``CaseReport``.
    """

    type: Literal["PERSON"]
    personId: int
    limsId: str | None = None
    familyId: str | None = None
    hpoTerms: list[str]  # only provided as string, can't reuse `HpoTerm` model here
    comment: str | None = None
    analyses: list[CaseReportAnalysis]
    active: bool


class CaseReportDisease(BaseModel):
    """
    Model representing a disease in a case report. Used in ``CaseReportConclusion``.

    TODO: must confirm which fields are optional and which are not
    """

    id: int
    shortName: str | None = None
    name: str
    omimId: int | None = None
    icd10Id: str | None = None
    orphanetId: int | str | None = None


class CaseReportGene(BaseModel):
    """
    Model representing a gene used in a case report. Used in ``CaseReportSnvConclusion`` and
    ``CaseReportCnvConclusion``.

    TODO: must confirm which fields are optional and which are not
    """

    id: int
    ncbiId: int | None = None
    omimId: int | None = None
    ensemblId: str | None = None
    hgncId: int | None = None
    lrgId: int | None = None
    symbol: str | None = None
    name: str
    transcript: str
    transcriptCdsLength: int
    transcriptExonCount: int
    chromosome: str
    chromosomeLocation: str
    hpoTerms: list[str]


class CaseReportCnvConclusion(BaseModel):
    """
    Model representing a CNV conclusion in a case report. Used in ``CaseReportConclusion``.
    """

    analysisIds: list[int]
    significance: VariantSignificance
    variant: str
    cdna: str | None = None
    hgvs: str
    iscn: str
    position: GenomicPosition
    copyNumber: int
    type: Literal["LOSS", "GAIN"]
    mosaic: bool
    length: int
    log2: float
    refSpread: float
    affectedGenes: list[CaseReportGene]
    transcripts: list[str]
    exons: list[int]
    latestComment: str | None = None
    commentCount: int
    annotations: CnvAnnotations


class CaseReportSnvConclusion(BaseModel):
    """
    Model representing an SNV conclusion for a case report. Used in ``CaseReportConclusion``.

    TODO: must confirm which fields are optional and which are not
    """

    analysisIds: list[int]
    significance: VariantSignificance
    genes: list[CaseReportGene]
    cdna: str
    position: GenomicPosition
    transcript: str
    variant: str
    acmgVersion: str
    acmgCriteria: list[str]
    latestComment: str | None = None
    commentCount: int
    annotations: dict[str, int | float | str | list[int | float | str] | None]
    selectedPaper: list[str]


class CaseReportConclusion(BaseModel):
    """
    Model representing a case report conclusion. Used in ``CaseReportVirtualPanelItem``.

    .. note:: API documentation says that there's a field ``disease`` *and* a field ``diseases``.
    """

    diseases: list[CaseReportDisease]
    modeOfInheritance: str
    genotype: str
    clinicalAssessment: str
    comment: str | None = None
    variantCategory: str
    cnvConclusions: list[CaseReportCnvConclusion]
    snvConclusions: list[CaseReportSnvConclusion]
    disease: CaseReportDisease


class CaseReportAppliedFilter(BaseModel):
    """
    Model representing an applied filter for a case report. Used in ``CaseReportVirtualPanelItem``.
    """

    name: str
    filter: str


class CaseReportVirtualPanelItem(BaseModel):
    """
    Model representing a virtual panel item for a case report.  Used in ``CaseReport``.
    """

    type: Literal["VIRTUAL_PANEL"]
    allGenesPanel: bool
    virtualPanelId: int
    name: str
    genes: list[CaseReportGene]
    appliedFilters: list[CaseReportAppliedFilter]
    conclusions: list[CaseReportConclusion]
    active: bool


class CaseReportMethodsItem(BaseModel):
    """
    Model representing a methods item for a case report. Used in ``CaseReport``.
    """

    type: Literal["METHODS"]
    analyses: list[CaseReportAnalysis]
    active: bool


class CaseReport(BaseModel):
    """
    Model representing a complete case report as returned from varvis *Get Case Report* endpoint.

    API documentation states that all fields apart from ``items`` are optional.
    """

    draft: bool | None = None
    personId: int | None = None  # internal person ID (not LIMS-ID)
    submitter: str | None = None
    submitted: datetime | None = None
    approver: str | None = None
    approved: datetime | None = None
    title: str | None = None
    comment: str | None = None
    reportState: str | None = (
        None  # TODO: may be possible to narrow this to set of discrete states
    )
    items: list[
        Annotated[
            CaseReportVirtualPanelItem | CaseReportMethodsItem | CaseReportPersonItem,
            Field(discriminator="type"),
        ]
    ]


class VirtualPanelSummary(BaseModel):
    """
    Model representing information about a virtual panel as returned from varvis *Get Virtual Panel Summaries* endpoint.

    Generated from playground samples and API documentation.
    """

    id: int
    name: str
    numberOfGenesInPanel: int
    lengthOfTranscriptsCds: int
    active: bool | None = None
    description: str | None = None
    personId: int | None = None
    creator: str | None = None
    creationTime: datetime | None = None
    usageCount: int | None = None


class VarvisGene(BaseModel):
    """
    Model representing a gene used in Varvis for the *Get All Genes* endpoint.

    Generated from playground samples and API documentation.
    """

    id: int
    ncbiId: int
    omimId: int | None = None
    ensemblId: str | None = None
    hgncId: int | None = None
    lrgId: int | None = None
    symbol: str
    name: str
    transcript: str | None = None
    transcriptCdsLength: int
    transcriptExonCount: int
    chromosome: str
    chromosomeLocation: str
    hpoTerms: list[str]


class VirtualPanelData(BaseModel):
    """
    Model representing a virtual panel as returned from *Get Virtual Panel Details* endpoint.

    Generated from API documentation and playground samples.
    """

    id: int | None = None  # strangely, the API says the ID is optional
    name: str
    active: bool
    genes: list[VarvisGene]
    description: str | None
    personId: int | None


class VirtualPanelUpdateData(BaseModel):
    """
    Model for creating or updating a virtual panel using the *Create Or Update Virtual Panel* endpoint.

    Updates an existing or creates a new virtual panel based on the information provided. In order to create a new
    virtual panel no id must be specified. If an id is specified it must belong to an existing virtual panel.

    Generated from API documentation.
    """

    id: int | None = Field(
        default=None,
        description="The virtual panel id. In order to create a new virtual panel no id must be specified. If an id "
        "is specified it must belong to an existing virtual panel.",
    )
    name: str = Field(description="The virtual panel name.")
    active: bool = Field(
        description="The virtual panel active state, if not active it can't be used."
    )
    geneIds: list[int] = Field(
        description="Gene ids of genes that should be associated with this virtual panel."
    )
    description: str | None = Field(
        default=None, description="Optional description of the virtual panel."
    )
    personId: int | None = Field(
        default=None, description="Optional id of the bound person."
    )


class ApiFileLink(BaseModel):
    """
    Model representing a downloadable file used in ``AnalysisFileDownloadLinks`` model.

    Varvis API documentation states that all fields are optional (which is rather strange).
    """

    fileName: str | None = None
    downloadLink: str | None = None
    estimatedRestoreTime: str | None = None
    currentlyArchived: bool | None = None


class AnalysisFileDownloadLinks(BaseModel):
    """
    Model representing a response from the *Get File Download Links* endpoint.

    Generated from sample responses and updated from Varvis API documentation.
    """

    id: int  # analysis ID
    sampleId: str | None = None
    limsId: str | None = None
    customerProvidedInputFilePaths: list[str]
    apiFileLinks: list[ApiFileLink]
