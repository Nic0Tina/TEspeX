#! /home/fansalon/Software/Python-3.6.5/bin/bin/python3
import sys
import time
import os
from os import listdir
import argparse
import gzip
import subprocess
import math
import pysam
import pandas
from functools import reduce

# 1.
# define the help function
def help():
  # define 2 global variables because they will be used by more than 2 functions
  global dir
  global num_threads
  global bin_path

  # dir from which the script has been launched. This will be usefull to call all the other softwares that should be in the bin/ folder
  bin_path = os.path.dirname(os.path.realpath(__file__)) + "/bin/"

  parser = argparse.ArgumentParser()
  
  # create argument list
  parser.add_argument('--TE', type=str, help='fa/fa.gz file containing TE consensus sequences [required]', required=True)
  parser.add_argument('--cdna', type=str, help='fa/fa.gz file containing cdna Ensembl sequences [required]', required=True)
  parser.add_argument('--ncrna', type=str, help='fa/fa.gz file containing ncrna Ensembl sequences [required]', required=True)
  parser.add_argument('--sample', type=str, help='txt file containing fq/fq.gz FULL PATHS. If reads are single end, one path should be written in each line. If reads are paired end the two mates should be written in the same line separated by \\t [required]', required=True)
  parser.add_argument('--paired', type=str, help='T (true) or F (false) [required]', required=True)
  parser.add_argument('--length', type=int, help='length of the read given as input. This is used to calculate STAR index parameters [required]', required=True)
  parser.add_argument('--out', type=str, help='directory where the output files will be written', required=True)
  parser.add_argument('--num_threads', type=int, default=2, help='number of threads used by STAR and samtools [2]', required=False)
  parser.add_argument('--remove', type=str, default='T', help='if this parameter is set to T all the bam files are removed. If it is F they are not removed [T]', required=False)

  # create arguments
  arg = parser.parse_args()
  te = os.path.abspath(arg.TE)
  cDNA = os.path.abspath(arg.cdna)
  ncRNA = os.path.abspath(arg.ncrna)
  sample_file = os.path.abspath(arg.sample)
  prd = arg.paired
  rl = arg.length
  dir = os.path.abspath(arg.out)
  num_threads = arg.num_threads
  rm = arg.remove

#  global dir

  # create the outDir
  while True:
    try:
      os.mkdir(dir)
      break
    except FileExistsError:
      print("ERROR: "+dir+" directory already exists")
      sys.exit()
  

  # create a list with the arguments that are files
  argList = []
  argList.append(te)
  argList.append(cDNA)
  argList.append(ncRNA)
  argList.append(sample_file)
  # check that the input files exist
  for i in range(0, len(argList)):
    if os.path.isfile(argList[i]):
      continue
    else:
      print("ERROR!\n%s: no such file or directory" % (argList[i]))
      sys.exit()

  return te, cDNA, ncRNA, sample_file, prd, rl, dir, num_threads, rm, bin_path


# 2.
# this function writes the message to the log file in the output directory
def writeLog(message):
  with open(dir+"/Log.file.out", 'a') as logfile:
    logfile.write("[%s] " % (time.asctime()))
    logfile.write("%s\n" % (message))

# 3.
# this function takes as input a string containing a shell command and executes it
def bash(command):
  cmd = subprocess.Popen(command, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
  writeLog("executing: %s" % (command))
  err, out = cmd.communicate()
  if int(cmd.returncode) != 0:
    print("Error in", command)
    print(err.decode("UTF-8"))
    print(out.decode("UTF-8"))
    sys.exit()

# 4.
# this function takes as input 3 fasta files: TE, ensembl-cdna, ensembl-ncrna, adds _transc and _transp to fasta names 
# and merge the 3 files together creating the reference
def createReference(fasta, tag):
  # this function takes a line of a fasta file and return the name+tag or the nt sequence
  def lineSplitting(riga):
    if '>' in riga:
      riga_new = riga.split()[0] + tag
    else:
      riga_new = riga.split("\t")[0]  
    return riga_new

  with open(dir+"/TE_transc_reference.fa",'a') as output:
    # for each arguments of the function, unzip the file if it is zipped
    path_filename, file_extension = os.path.splitext(fasta)
    if file_extension == ".gz":
      writeLog("detected zipped file: %s" % (fasta))
      with gzip.open(fasta, 'rb') as f:
        for lineZIP in f:
          line = lineZIP.decode('utf8').strip()
          line_new = lineSplitting(line)
          output.write("%s\n" % (line_new))
    else:
      with open(fasta) as f:
        for line in f:
          line_new = lineSplitting(line)
          output.write("%s\n" % (line_new))

  fastaRef = (os.path.abspath(dir+"/TE_transc_reference.fa"))

  return fastaRef

# 5.
# convert fasta to bed (TE)
def faTObed(fasta):
  faidx_com = bin_path + "samtools-1.3.1/samtools faidx " + fasta 
  bash(faidx_com)
  # convert the fai file in bed format using pandas
  fai = pandas.read_table(fasta+".fai", sep='\t', header=None)
  faiTE = fai[fai[0].str.contains("_transp")]
  fai_bed = faiTE.iloc[:, [0,1] ]
  fai_bed.insert(1,'start',0)		# add the column with the start value
  fai_bed.to_csv(fasta+".bed",sep='\t',index=False, header=False)

  bedRef = (os.path.abspath(fasta+".bed"))

  return bedRef

# 6.
# this function creates the index of the reference file
def star_ind(genome, r_length):
  # to avoid STAR segmentation fault calculate genomeSAindexNbases and genomeChrBinNbits parameters
  readL = int(r_length)

  bed = pandas.read_table(genome+".fai", sep='\t', header=None)
  genome_length = sum(bed.iloc[:,1])
  chrom = len(bed.iloc[:,0])

  # now calculate the parameters for STAR
  genomeSAindexNbase = int(min(14, (math.log2(genome_length)) / 2 - 1))
  genomeChrBinNbits = int(min(18, math.log2(max(genome_length/chrom,readL))))

  # create dir where write indexes
  os.mkdir("index")
  os.chdir("index")
  # then we can call the STAR index function using the number of threads that is passed from command line
  starCmd = bin_path + "STAR-2.6.0c/bin/Linux_x86_64/STAR --runThreadN " +str(num_threads)+ " --runMode genomeGenerate --genomeDir " +os.path.abspath(".")+ " --genomeFastaFiles " +genome+ " --genomeSAindexNbases " +str(genomeSAindexNbase)+ " --genomeChrBinNbits " +str(genomeChrBinNbits)
  bash(starCmd)
  
  os.chdir(dir)

# 7.
# map the reads to the reference. The argument of this function is a file with the full path to the reads
# if the reads are paired they are written on the same line separated by \t
def star_aln(fq_list, bedReference, pair, rm):
  output_names = []				# this is the list that will contain the names of the bedtools coverage output files
  statOut = []					# this is the list that will contain mapping statistics
  statOut.append("SRR\ttot\tmapped\tTE-best\tspecificTE\tnot_specificTE")

  # define the general command (no reads and no zcat)
  command = bin_path "STAR-2.6.0c/bin/Linux_x86_64/STAR --outSAMunmapped None --outSAMprimaryFlag AllBestScore --outFilterMismatchNoverLmax 0.04 --outMultimapperOrder Random --outSAMtype BAM Unsorted --outStd BAM_Unsorted --runThreadN " +str(num_threads)+ " --genomeDir " +os.path.abspath("index")
  # for every line of the file launch the analysis
  with open(fq_list) as reads:
    for line in reads:
      writeLog("\n\nI am working with %s" % (line[:-1]))
      os.chdir(dir)
      lin = line.split()

      path_filename, file_extension = os.path.splitext(lin[0])	# separate full_path+file and extension
      filenam = os.path.basename(path_filename)			# extrapolate filename without full_path and extension 
      filename = os.path.splitext(filenam)[0]			# (if the file is fq.gz .fq will remain in filenam)
      os.mkdir(filename)					# (if the file is fq.gz .fq will remain in filenam)
      os.chdir(filename)

      # single end
      if len(lin) == 1:
        writeLog("single end reads detected")
        if len(lin) == 1 and pair == "T":
          writeLog("ERROR: %s file contains SE reads but you specify PE reads from command line. Exiting.." % (fq_list))
          print("ERROR: %s file contains SE reads but you specify PE reads from command line. Exiting.." % (fq_list))
          sys.exit()
        if file_extension == ".gz":
          gzipped = True
          command_final = command + " --readFilesIn " +lin[0]+ " --readFilesCommand zcat > " +filename+ ".bam"
        else:
          gzipped =False
          command_final = command + " --readFilesIn " +lin[0]+ " > " +filename+ ".bam"
      # paired end
      elif len(lin) == 2:
        writeLog("paired end reads detected")
        if len(lin) == 2 and pair == "F":
          writeLog("ERROR: %s file contains PE reads but you specify SE reads from command line. Exiting.." % (fq_list))
          print("ERROR: %s file contains PE reads but you specify SE reads from command line. Exiting.." % (fq_list))
          sys.exit()
        if file_extension == ".gz":
          gzipped = True
          command_final = command + " --readFilesIn " +lin[0]+ " " +lin[1]+ " --readFilesCommand zcat > "+filename+ ".bam"
        else:
          gzipped = False
          command_final = command + " --readFilesIn " +lin[0]+ " " +lin[1]+ " > " +filename+ ".bam"
    # 7.1 
    # map reads to reference  
      bash(command_final)
    
    # 7.2  
    # extract primary alignments (best score alignments)
      prim_cmd = bin_path + "samtools-1.3.1/samtools view -@ " +str(num_threads)+ " -b -F 0x100 -o " +filename+ "_mappedPrim.bam " +filename+ ".bam"
      bash(prim_cmd)

    # 7.3  
    # create list containing name of the reads mapping with best score alignmets only on TEs. These reads are mapping specifically on TEs
      writeLog("selecting reads mapping specifically on TEs")
      TE = []
      mrna = []
      bamfile = pysam.AlignmentFile(filename+"_mappedPrim.bam", "rb")
      for aln in bamfile.fetch(until_eof=True):
        if "_transc" in aln.reference_name:
          mrna.append(aln.query_name)
        elif "_transp" in aln.reference_name:
          TE.append(aln.query_name)
      bamfile.close()
      final = list( set(TE) - set(mrna) ) 			# these reads map with best score only on TEs and not on transcripts
      not_specific = list( set(TE) - set(final) )		# these reads map with best score on both TEs and transcripts

      # write the 2 lists in 2 output files
      with open("specificTE.txt", 'w') as out1:
        for i in range(0, len(final)):
          out1.write("%s\n" % (final[i]))
      with open("not-specificTE.txt", 'w') as out2:
        for j in range(0, len(not_specific)):
          out2.write("%s\n" % (not_specific[j]))

    # 7.4
    # usem picard to extract alignmets corresponing to reads mapping specifically on TEs
      picard = bin_path + "jre1.8.0_144/bin/java -jar " + bin_path + "picard/picard.jar FilterSamReads I="+filename+"_mappedPrim.bam O="+filename+"_specificTE.bam FILTER=includeReadList RLF=specificTE.txt"
      bash(picard)

    # 7.5
    # count the reads mapping specifically on TEs using bedtools coverage
      with open(filename+ "_counts", 'w') as header:
        header.write("TE\t%s\n" % (filename))
      bedt = bin_path + "bedtools-2.26.0/bedtools2/bin/bedtools coverage -counts -a " +bedReference+ " -b " +filename+"_specificTE.bam | awk '{ print $1 \"\\t\" $4 }' >> " +filename+ "_counts"
      bash(bedt)
      # append the name of the bedtools coverage output in the list
      output_names.append(os.path.abspath(".")+"/"+filename+ "_counts")

    # 7.6
    # create a file with statistics
      # total reads
      writeLog("calculating the mapping statistics...")
      if gzipped == True:
        count = int(subprocess.check_output("zcat " + lin[0] + " | wc -l", shell=True)) # bash zcat is faster than python .gzip
        tot = str(int(count/4))
      else:
        count = int(subprocess.check_output("cat " + lin[0] + " | wc -l", shell=True)) 
        tot = str(int(count/4))
      # mapped
      read_list = []
      samfile = pysam.AlignmentFile(filename+".bam", "rb")
      for aln in samfile.fetch(until_eof=True):
        read_list.append(aln.query_name)
      samfile.close()
      map = len(list(set(read_list)))
      # reads mapped on TEs
      mapTE = len(final) + len(not_specific)
      # reads specifically mapped against TE
      specific = len(final)
      # reads not specifically mapped against TE
      not_spec = len(not_specific)
      # write into output list
      riga_stat = str(filename)+"\t"+str(tot)+"\t"+str(map)+"\t"+str(mapTE)+"\t"+str(specific)+"\t"+str(not_spec)
      statOut.append(riga_stat)

      # remove the bam files
      if rm == 'T':
        os.remove(filename+".bam")
        os.remove(filename+ "_mappedPrim.bam")
        os.remove(filename+"_specificTE.bam")

  return output_names, statOut  

# 8.
# this function takes as input the list 'out' containing the full path to bedtools coverage output files
# and the list 'stat' containing the mapping statitistics for each fq analyzed and write the 2 lists
# in 2 output files
def createOut(out, stat):
  pd = []
  for count in out:
    pdFile = pandas.read_table(count,sep='\t',header=0)
    pd.append(pdFile)
  count_final = reduce(lambda left,right: pandas.merge(left,right,on='TE'), pd)
  count_final.to_csv(dir+"/outfile.txt",sep='\t',index=False,float_format='%.2f')
  
  # create the output file with mapping statistics
  with open(dir+"/mapping_stats.txt", 'w') as mapS:
    for i in range(0, len(stat)):
      mapS.write("%s\n" % (stat[i]))

  writeLog("DONE")

# 9.
# main
def main():
  TE, cdna, ncrna, sample, paired, read_length, dir, num_threads, remove, bin_path = help()
  os.chdir(dir)
  writeLog("\nuser command line arguments:\nTE file = %s\ncdna file = %s\nncrna file = %s\nsampleFile file = %s\npaired = %s\nreadLength = %s\noutDir = %s\nnum_threads = %s \nremove = %s\n" % (TE, cdna, ncrna, sample, paired, read_length, dir, num_threads, remove))
  writeLog("creating reference file %s/TE_transc_reference.fa" % (dir))
  createReference(TE, "_transp") 
  createReference(cdna, "_transc") 
  reference = createReference(ncrna, "_transc") 
  bedReference = faTObed(reference)
  star_ind(reference, read_length)
  outfile, statfile = star_aln(sample, bedReference, paired, remove)
  createOut(outfile, statfile)


if __name__ == "__main__":
  main()